#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : curd_media.py
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from common.curd_base import CRUDBase
from ..models.curated_media import CuratedMedia


class CURDCuratedMedia(CRUDBase):
    def getByProviderMediaId(self, db: Session, provider_code: str, media_id: str,
                             include_deleted: bool = False) -> dict:
        """按 (站点, 媒体id) 查一条记录。

        :param include_deleted: True 时连"已软删除"的记录一起查(活跃记录优先),
                                用于重新入库时复用同一行(维持唯一约束)。
        """
        q = db.query(*self.query_columns, self.model.is_deleted).filter(
            self.model.provider_code == provider_code,
            self.model.media_id == media_id,
        )
        if include_deleted:
            q = q.order_by(self.model.is_deleted.asc(), self.model.id.asc())
        else:
            q = q.filter(self.model.is_deleted == 0)
        obj = q.first()
        return dict(obj or {})

    def getMapByProviderMediaIds(self, db: Session, provider_code: str,
                                 media_ids: List[str],
                                 include_deleted: bool = False) -> Dict[str, dict]:
        """一次查出多个 media_id 的记录 -> {media_id: row}

        批量入库前用来去重, 避免逐条查询。
        :param include_deleted: True 时会返回"已软删除"的记录(活跃记录优先),
                                用于重新入库时复活旧行而不是新增一行。
        """
        media_ids = [str(m) for m in (media_ids or []) if m]
        if not media_ids:
            return {}
        q = db.query(*self.query_columns, self.model.is_deleted).filter(
            self.model.provider_code == provider_code,
            self.model.media_id.in_(media_ids),
        )
        if include_deleted:
            # 小到大: is_deleted=0(活跃) 优先, 其次 id 最小
            q = q.order_by(self.model.media_id.asc(), self.model.is_deleted.asc(),
                           self.model.id.asc())
        else:
            q = q.filter(self.model.is_deleted == 0)
        result: Dict[str, dict] = {}
        for o in q.all():
            # 同一 media_id 只保留第一条(活跃/最新)
            result.setdefault(str(o.media_id), dict(o))
        return result

    def _applyUpsert(self, db: Session, _id: int, obj_in: Dict[str, Any],
                     modifier_id: int = 0) -> None:
        """就地更新并强制复活(is_deleted=0)。

        注意: 基类 update() 的 WHERE 带 `is_deleted != 1`, 无法复活被软删的行,
        这里直接构造 update, 不经过基类。
        """
        from fastapi.encoders import jsonable_encoder
        from common.curd_base import custom_encoder_dict_fn
        data = jsonable_encoder(obj_in, custom_encoder={dict: custom_encoder_dict_fn})
        values = {getattr(self.model, k): v for k, v in data.items() if hasattr(self.model, k)}
        values[self.model.is_deleted] = 0
        values[self.model.modifier_id] = modifier_id
        db.query(self.model).filter(self.model.id == _id).update(values)
        db.commit()

    def upsertByProviderMediaId(self, db: Session, provider_code: str, media_id: str,
                                obj_in: Dict[str, Any], creator_id: int = 0) -> Tuple[int, bool]:
        """按 (provider_code + media_id) 唯一写入(CREATE or REVIVE/UPDATE)。

        - 命中已有记录(含曾被软删除的) -> 就地更新并置 is_deleted=0(复活), 保证一行一条;
        - 未命中 -> 插入;
        - 并发同时插入触发唯一约束冲突时, 回滚后改走更新(应用层兑底)。
        :return: (本地 id, 是否为新插入)
        """
        from sqlalchemy.exc import IntegrityError
        row = self.getByProviderMediaId(db, provider_code, media_id, include_deleted=True)
        if row:
            self._applyUpsert(db, int(row['id']), obj_in, modifier_id=creator_id)
            return int(row['id']), False
        try:
            obj = self.create(db, obj_in={**obj_in, 'provider_code': provider_code,
                                          'media_id': media_id},
                              creator_id=creator_id)
            return int(obj.id), True
        except IntegrityError:
            # 并发下另一个请求已插入: 回滚后按更新处理
            db.rollback()
            row = self.getByProviderMediaId(db, provider_code, media_id, include_deleted=True)
            if not row:
                raise
            self._applyUpsert(db, int(row['id']), obj_in, modifier_id=creator_id)
            return int(row['id']), False

    def queryList(self, db: Session, *, provider_code: Optional[str] = None,
                  category_id: Optional[int] = None, status: Optional[int] = None,
                  visible: Optional[int] = None, keyword: Optional[str] = None,
                  extra_filters: Optional[List] = None,
                  page: int = 1, page_size: int = 25
                  ) -> Tuple[List[dict], int, int, int]:
        # extra_filters: 由调用方预先构造的附加过滤(如数据范围), 参与分页计数
        filters = list(extra_filters or [])
        if provider_code:
            filters.append(self.model.provider_code == provider_code)
        if category_id is not None:
            filters.append(self.model.category_id == category_id)
        if status is not None:
            filters.append(self.model.status == status)
        if visible is not None:
            filters.append(self.model.visible == visible)
        if keyword:
            like = f"%{keyword}%"
            filters.append(or_(self.model.title.ilike(like), self.model.up_name.ilike(like),
                               self.model.media_id.ilike(like)))
        order_bys = [self.model.order_num.asc(), self.model.id.desc()]
        return self.get_multi(db, filters=filters, order_bys=order_bys, page=page, page_size=page_size)

    def getVisibleList(self, db: Session, *, provider_code: Optional[str] = None,
                       category_id: Optional[int] = None) -> List[dict]:
        """供运行时源使用: 仅返回已通过且前台可见的媒体"""
        filters = [self.model.status == 1, self.model.visible == 1]
        if provider_code:
            filters.append(self.model.provider_code == provider_code)
        if category_id is not None:
            filters.append(self.model.category_id == category_id)
        objs = db.query(*self.query_columns).filter(
            *filters, self.model.is_deleted == 0
        ).order_by(self.model.order_num.asc(), self.model.id.desc()).all()
        return [dict(o) for o in objs]

    def getVisibleById(self, db: Session, _id: int):
        obj = db.query(*self.query_columns).filter(
            self.model.id == _id, self.model.status == 1, self.model.visible == 1,
            self.model.is_deleted == 0,
        ).first()
        return dict(obj or {})


curd_curated_media = CURDCuratedMedia(CuratedMedia)
