#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : curd_episode.py
from typing import List
from sqlalchemy.orm import Session

from common.curd_base import CRUDBase
from ..models.curated_episode import CuratedEpisode


class CURDCuratedEpisode(CRUDBase):
    def getByMediaId(self, db: Session, media_id: int):
        objs = db.query(*self.query_columns).filter(
            self.model.media_id == media_id, self.model.is_deleted == 0
        ).order_by(self.model.order_num).all()
        return [dict(o) for o in objs]

    def getByMediaIds(self, db: Session, media_ids: List[int]):
        if not media_ids:
            return []
        objs = db.query(*self.query_columns).filter(
            self.model.media_id.in_(media_ids), self.model.is_deleted == 0
        ).order_by(self.model.media_id, self.model.order_num).all()
        return [dict(o) for o in objs]

    def deleteByMediaId(self, db: Session, media_id: int):
        db.query(self.model).filter(self.model.media_id == media_id).delete()
        db.commit()

    def replaceByMediaId(self, db: Session, media_id: int, episodes: List[dict]) -> int:
        """删除旧选集并批量写入新选集(单次提交)

        逐集 create() 会导致每集一次 commit, 上千集时产生上千次磁盘同步(极慢),
        这里改为 add_all + 一次 commit。
        :return: 写入的选集条数
        """
        db.query(self.model).filter(self.model.media_id == media_id).delete()
        rows = []
        for idx, ep in enumerate(episodes or []):
            rows.append(self.model(
                media_id=media_id,
                page_index=ep.get('page_index', idx),
                cid=str(ep.get('cid') or ''),
                title=ep.get('title') or f'P{idx + 1}',
                duration=int(ep.get('duration') or 0),
                order_num=ep.get('order_num', idx),
            ))
        if rows:
            db.add_all(rows)
        db.commit()
        return len(rows)


curd_curated_episode = CURDCuratedEpisode(CuratedEpisode)
