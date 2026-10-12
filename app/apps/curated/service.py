#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : service.py
# 精选内容 - 业务服务层
"""
供两类调用方使用:
1. 后台 API (views): 传入已有 db session
2. 运行时 TVBox 源 (t4/spiders/亲子精选.py): 不传 db, 自动开关 session

注意: 任何密钥(cookie)都只存于数据库, 不写入 web 可访问的目录。
"""
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from core.logger import logger
from db.session import SessionLocal
from .curd import (curd_curated_provider, curd_curated_category,
                   curd_curated_media, curd_curated_episode)
from .classifier import classify_title
from .providers import get_provider, list_providers


@contextmanager
def _session(db: Optional[Session] = None):
    if db is not None:
        yield db
        return
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _is_active(row: Optional[dict]) -> bool:
    """记录存在且未被软删除"""
    return bool(row) and not int(row.get('is_deleted') or 0)


class CuratedService:

    # ------------------------------------------------------------------
    # config 规范化
    # ------------------------------------------------------------------
    @staticmethod
    def parse_config(cfg) -> dict:
        if not cfg:
            return {}
        if isinstance(cfg, dict):
            return cfg
        try:
            data = json.loads(cfg)
            return data if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            return {}

    @staticmethod
    def dump_config(cfg) -> str:
        if cfg is None:
            return ""
        if isinstance(cfg, str):
            # 校验一下是否是合法 json, 不合法则原样保存
            try:
                json.loads(cfg)
                return cfg
            except (ValueError, TypeError):
                return json.dumps({}, ensure_ascii=False)
        return json.dumps(cfg, ensure_ascii=False)

    def list_providers(self) -> List[dict]:
        return list_providers()

    # ------------------------------------------------------------------
    # provider 实例
    # ------------------------------------------------------------------
    def get_provider_instance(self, db: Session, code: str):
        rec = curd_curated_provider.getByCode(db, code)
        if not rec:
            raise ValueError(f"站点 {code} 未配置")
        config = self.parse_config(rec.get('config'))
        provider = get_provider(code, config)
        if not provider:
            raise ValueError(f"不支持的站点编码: {code}")
        return provider

    def get_provider_config(self, db: Session, code: str) -> dict:
        rec = curd_curated_provider.getByCode(db, code)
        return self.parse_config(rec.get('config')) if rec else {}

    # ------------------------------------------------------------------
    # 搜索 / 解析 / 校验
    # ------------------------------------------------------------------
    def search(self, provider_code: str, keyword: str, page: int = 1, page_size: int = 20,
               db: Optional[Session] = None) -> dict:
        with _session(db) as _db:
            provider = self.get_provider_instance(_db, provider_code)
            result = provider.search(keyword, page=page, page_size=page_size)
            # 标注是否已入库
            for it in result.get('list', []):
                exist = curd_curated_media.getByProviderMediaId(_db, provider_code, it.get('media_id'))
                it['imported'] = bool(exist)
                it['local_id'] = exist.get('id') if exist else None
            return result

    def resolve(self, provider_code: str, url: str, db: Optional[Session] = None) -> dict:
        with _session(db) as _db:
            provider = self.get_provider_instance(_db, provider_code)
            item = provider.resolve_url(url)
            exist = curd_curated_media.getByProviderMediaId(_db, provider_code, item.get('media_id'))
            item['imported'] = bool(exist)
            item['local_id'] = exist.get('id') if exist else None
            return item

    def test_config(self, code: str, config=None, db: Optional[Session] = None) -> dict:
        if config is None:
            with _session(db) as _db:
                config = self.get_provider_config(_db, code)
        provider = get_provider(code, self.parse_config(config) if not isinstance(config, dict) else config)
        if not provider:
            return {'ok': False, 'message': f'不支持的站点编码: {code}', 'info': {}}
        return provider.test()

    def check_viewable(self, provider_code: str, media_id: str, db: Optional[Session] = None) -> dict:
        with _session(db) as _db:
            provider = self.get_provider_instance(_db, provider_code)
            return provider.check_viewable(media_id)

    # ------------------------------------------------------------------
    # 入库
    # ------------------------------------------------------------------
    def _save_episodes(self, _db: Session, local_id: int, episodes: List[dict]):
        # 批量写入(单次提交): 部分合集有上千集, 逐集 create() 会极慢
        curd_curated_episode.replaceByMediaId(_db, local_id, episodes)

    def import_media(self, item: dict, *, category_id: Optional[int] = None,
                     status: int = 1, visible: int = 1, provider_code: Optional[str] = None,
                     refresh: bool = True, creator_id: int = 0,
                     db: Optional[Session] = None,
                     detail: Optional[dict] = None,
                     exist: Optional[dict] = None) -> dict:
        """新增/更新一条媒体(按 provider_code + media_id 去重)

        :param detail: 已预先拉取好的详情(批量入库时并发获取), 非 None 则不再联网
        :param exist:  已存在的本地记录(批量入库时一次性查出), 非 None 则不再查询
        """
        with _session(db) as _db:
            code = provider_code or item.get('provider_code')
            media_id = item.get('media_id')
            if not code or not media_id:
                raise ValueError('缺少 provider_code 或 media_id')
            provider = self.get_provider_instance(_db, code)

            # 需要详情(选集)时拉取一次
            if detail is None:
                detail = item
                if refresh and not item.get('episodes'):
                    try:
                        detail = provider.get_detail(media_id)
                    except Exception as e:  # noqa
                        logger.warning(f'[curated] 拉取详情失败 {code}/{media_id}: {e}')

            if exist is None:
                exist = curd_curated_media.getByProviderMediaId(_db, code, media_id,
                                                              include_deleted=True)
            payload = {
                'provider_code': code,
                'media_id': media_id,
                'title': detail.get('title') or item.get('title') or media_id,
                'cover': detail.get('cover') or item.get('cover') or '',
                'description': detail.get('description') or item.get('description') or '',
                'duration': int(detail.get('duration') or item.get('duration') or 0),
                'up_name': detail.get('up_name') or item.get('up_name') or '',
                'up_mid': str(detail.get('up_mid') or item.get('up_mid') or ''),
                'source_url': detail.get('source_url') or item.get('source_url') or '',
                'extra': json.dumps(detail.get('extra') or item.get('extra') or {}, ensure_ascii=False),
                'play_count': int(detail.get('play_count') or item.get('play_count') or 0),
            }
            if category_id is not None:
                payload['category_id'] = category_id
            if status is not None:
                payload['status'] = status
            if visible is not None:
                payload['visible'] = visible

            # 唯一写入: 命中(含曾被软删除的)则更新+复活, 否则新增。
            # 数据库层有 UNIQUE(provider_code, media_id) 兼底。
            if not exist:
                payload['order_num'] = curd_curated_media.getMaxOrderNum(_db) + 1
            local_id, is_new = curd_curated_media.upsertByProviderMediaId(
                _db, code, media_id, payload, creator_id=creator_id)

            episodes = detail.get('episodes')
            if episodes:
                self._save_episodes(_db, local_id, episodes)
            return {'id': local_id, 'media_id': media_id, 'is_new': is_new}

    def _fetch_details(self, provider, media_ids: List[str], max_workers: int = 8) -> Dict[str, dict]:
        """并发拉取多个媒体详情(纯网络 IO, 不触碰 DB/Session)

        逐条串行拉详情是入库慢的主因(每条约 1s), 这里用线程池并发;
        每个线程用独立的 provider 实例(各自独立的 requests.Session)。
        """
        media_ids = [m for m in (media_ids or []) if m]
        if not media_ids:
            return {}
        code = provider.code
        cfg = dict(provider.config or {})
        result: Dict[str, dict] = {}

        def work(mid):
            try:
                p = get_provider(code, cfg) or provider
                return mid, p.get_detail(mid)
            except Exception as e:  # noqa
                logger.warning(f'[curated] 拉取详情失败 {code}/{mid}: {e}')
                return mid, None

        workers = max(1, min(max_workers, len(media_ids)))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for mid, detail in ex.map(work, media_ids):
                if detail:
                    result[mid] = detail
        return result

    def batch_import(self, provider_code: str, items: List[dict], *, category_id: Optional[int] = None,
                     status: int = 1, visible: int = 1, creator_id: int = 0,
                     skip_existing: bool = True, refresh: bool = True,
                     db: Optional[Session] = None) -> dict:
        """批量入库(自动去重)

        - 已存在(provider_code + media_id)的记录默认跳过, 保证重复点击幂等且秒回;
        - 需要联网补详情的条目会并发拉取, 大幅缩短等待时间。
        """
        items = [dict(it or {}) for it in (items or [])]
        errors, valid = [], []
        for it in items:
            it.setdefault('provider_code', provider_code)
            if not it.get('media_id'):
                errors.append({'item': it, 'error': '缺少 media_id'})
            else:
                valid.append(it)

        success, skipped = [], []
        created = updated = 0

        with _session(db) as _db:
            provider = self.get_provider_instance(_db, provider_code)
            exist_map = curd_curated_media.getMapByProviderMediaIds(
                _db, provider_code, [it['media_id'] for it in valid], include_deleted=True)

            # 1) 挑出需要联网补详情的条目
            need = []
            for it in valid:
                mid = it['media_id']
                if it.get('episodes'):
                    continue
                exist = exist_map.get(mid)
                if _is_active(exist) and skip_existing:
                    continue  # 已存在且跳过 -> 不需要刷新详情
                if _is_active(exist) and not refresh:
                    continue
                need.append(mid)

            # 2) 并发拉详情
            detail_map = self._fetch_details(provider, need)

            # 3) 写库(保持单线程写; SQLAlchemy Session 不跨线程)
            for it in valid:
                mid = it['media_id']
                exist = exist_map.get(mid)
                if _is_active(exist) and skip_existing:
                    skipped.append({'id': exist.get('id'), 'media_id': mid,
                                    'title': exist.get('title'), 'is_new': False, 'skipped': True})
                    continue
                try:
                    res = self.import_media(it, category_id=category_id, status=status,
                                            visible=visible, provider_code=provider_code,
                                            refresh=refresh, creator_id=creator_id, db=_db,
                                            detail=detail_map.get(mid, it), exist=exist or {})
                    res['skipped'] = False
                    success.append(res)
                    if res['is_new']:
                        created += 1
                    else:
                        updated += 1
                except Exception as e:  # noqa
                    logger.warning(f'[curated] 入库失败 {mid}: {e}')
                    errors.append({'media_id': mid, 'error': str(e)})

        return {
            'success': success,
            'skipped': skipped,
            'errors': errors,
            'created': created,
            'updated': updated,
            'skipped_count': len(skipped),
            'failed': len(errors),
        }

    # ------------------------------------------------------------------
    # 分类: 按标题关键词智能归类
    # ------------------------------------------------------------------
    def auto_classify(self, ids=None, *, apply: bool = False, extra_filters=None,
                      modifier_id: int = 0, db: Optional[Session] = None) -> dict:
        """按标题关键词给【未分类】内容归类(供后台「智能归类」按钮使用)。

        - 只处理 category_id 为 NULL/0 的记录, 不会覆盖已有分类;
        - ids 非空时只处理这些 id;
        - extra_filters 用于叠加调用方的数据范围过滤;
        - apply=False 时只返回归类预览, 不写库。
        """
        model = curd_curated_media.model
        with _session(db) as _db:
            cats = {c['name']: c['id'] for c in curd_curated_category.getEnabledCategories(_db)}
            q = _db.query(model.id, model.title).filter(
                model.is_deleted == 0,
                or_(model.category_id.is_(None), model.category_id == 0),
            )
            if ids:
                q = q.filter(model.id.in_([int(i) for i in ids]))
            if extra_filters:
                q = q.filter(*extra_filters)
            rows = [{'id': r[0], 'title': r[1]} for r in q.all()]

            buckets: Dict[int, dict] = {}
            for row in rows:
                name = classify_title(row['title'])
                cid = cats.get(name)
                if cid is None:
                    logger.warning(f'[curated] 自动归类目标分类不存在, 已跳过: {name}')
                    continue
                buckets.setdefault(cid, {'category': name, 'items': []})['items'].append(row)

            plan, updated = [], 0
            for cid, bucket in sorted(buckets.items(), key=lambda kv: -len(kv[1]['items'])):
                items = bucket['items']
                plan.append({
                    'category': bucket['category'],
                    'category_id': cid,
                    'count': len(items),
                    'ids': [i['id'] for i in items],
                    'samples': [i['title'] for i in items[:10]],
                })
                if apply:
                    updated += _db.query(model).filter(
                        model.id.in_([i['id'] for i in items])
                    ).update({'category_id': cid, 'modifier_id': modifier_id},
                             synchronize_session=False)
            if apply and updated:
                _db.commit()
            return {'total': len(rows), 'updated': updated, 'applied': apply, 'plan': plan}

    # ------------------------------------------------------------------
    # 播放
    # ------------------------------------------------------------------
    def resolve_play(self, provider_code: str, media_id: str, cid: str = "", qn: int = 80,
                     db: Optional[Session] = None) -> dict:
        with _session(db) as _db:
            provider = self.get_provider_instance(_db, provider_code)
            return provider.resolve_play(media_id, cid, qn=qn)

    # ------------------------------------------------------------------
    # 可见性 / 可播放 校验
    # ------------------------------------------------------------------
    def check_media(self, local_id: int, db: Optional[Session] = None) -> dict:
        """校验单个媒体: 账号可见性 + 首集播放解析, 并写入校验结果"""
        with _session(db) as _db:
            media = curd_curated_media.get(_db, _id=local_id)
            if not media:
                return {'id': local_id, 'ok': False, 'viewable': False, 'playable': False,
                        'message': '内容不存在'}
            code = media.get('provider_code')
            result = {'id': local_id, 'media_id': media.get('media_id'), 'title': media.get('title'),
                      'ok': False, 'viewable': False, 'playable': False, 'quality': None,
                      'url': '', 'message': ''}
            try:
                provider = self.get_provider_instance(_db, code)
            except Exception as e:  # noqa
                result['message'] = str(e)
                return result
            try:
                v = provider.check_viewable(media.get('media_id'))
                result['viewable'] = bool(v.get('ok'))
                result['message'] = v.get('message') or ''
            except Exception as e:  # noqa
                result['message'] = f'可见性校验异常: {e}'
            if result['viewable']:
                try:
                    eps = curd_curated_episode.getByMediaId(_db, local_id)
                    cid = str(eps[0].get('cid') or '') if eps else ''
                    play = provider.resolve_play(media.get('media_id'), cid)
                    result['playable'] = bool(play.get('url'))
                    result['url'] = play.get('url') or ''
                    result['quality'] = play.get('quality')
                    if not result['message']:
                        result['message'] = '正常'
                except Exception as e:  # noqa
                    result['message'] = f'播放解析失败: {e}'
            result['ok'] = bool(result['viewable'] and result['playable'])
            try:
                curd_curated_media.update(_db, _id=local_id, obj_in={
                    'view_status': 1 if result['ok'] else 2,
                    'check_time': datetime.now(),
                })
            except Exception as e:  # noqa
                logger.warning(f'[curated] 写入校验结果失败: {e}')
            return result

    def check_batch(self, ids: List[int], db: Optional[Session] = None) -> dict:
        results = []
        ok_count = 0
        with _session(db) as _db:
            for _id in ids or []:
                try:
                    r = self.check_media(int(_id), db=_db)
                except Exception as e:  # noqa
                    r = {'id': _id, 'ok': False, 'message': str(e)}
                results.append(r)
                if r.get('ok'):
                    ok_count += 1
        return {'results': results, 'ok_count': ok_count,
                'fail_count': len(results) - ok_count, 'total': len(results)}

    # ------------------------------------------------------------------
    # 儿童专用订阅
    # ------------------------------------------------------------------
    def ensure_kid_subscription(self, reg: str = '亲子精选', code: str = 'qinzi01',
                                name: str = '亲子精选', db: Optional[Session] = None) -> dict:
        """确保存在一条只保留【亲子精选】源的订阅, 返回其订阅码"""
        from apps.vod.curd.curd_subs import curd_vod_subs
        with _session(db) as _db:
            rec = curd_vod_subs.getByName(_db, name)
            if rec:
                # 已存在则强制校正, 否则 mode/reg 不对会导致 /config 过滤失效(返回全部源)
                fix = {}
                if rec.reg != reg:
                    fix['reg'] = reg
                if rec.mode != 0:
                    fix['mode'] = 0
                if rec.status != 1:
                    fix['status'] = 1
                if fix:
                    curd_vod_subs.update(_db, _id=rec.id, obj_in=fix)
                    rec = curd_vod_subs.getByName(_db, name)
                return {'code': rec.code, 'name': rec.name, 'reg': rec.reg,
                        'mode': rec.mode, 'created': False}
            final_code = code
            if curd_vod_subs.getByCode(_db, final_code):
                final_code = code + 'a'
            obj = curd_vod_subs.create(_db, obj_in={
                'name': name, 'code': final_code, 'reg': reg, 'mode': 0, 'status': 1,
            })
            return {'code': obj.code, 'name': obj.name, 'reg': reg, 'mode': 0, 'created': True}

    # ------------------------------------------------------------------
    # 运行时(源)读取
    # ------------------------------------------------------------------
    def get_categories(self, db: Optional[Session] = None) -> List[dict]:
        with _session(db) as _db:
            return curd_curated_category.getEnabledCategories(_db)

    def get_media_list(self, category_id: Optional[int] = None, keyword: Optional[str] = None,
                       page: int = 1, page_size: int = 1000, db: Optional[Session] = None) -> List[dict]:
        with _session(db) as _db:
            if keyword:
                items, _, _, _ = curd_curated_media.queryList(
                    _db, status=1, visible=1, keyword=keyword, page=page, page_size=page_size)
            else:
                items = curd_curated_media.getVisibleList(_db, category_id=category_id)
            ids = [i['id'] for i in items]
            eps = curd_curated_episode.getByMediaIds(_db, ids)
            ep_map: Dict[int, List[dict]] = {}
            for e in eps:
                ep_map.setdefault(e['media_id'], []).append(e)
            for i in items:
                i['episodes'] = ep_map.get(i['id'], [])
            return items

    def get_media(self, local_id: int, db: Optional[Session] = None) -> dict:
        with _session(db) as _db:
            media = curd_curated_media.get(_db, _id=local_id)
            if not media:
                return {}
            media['episodes'] = curd_curated_episode.getByMediaId(_db, local_id)
            return media

    def get_media_detail(self, local_id: int, db: Optional[Session] = None) -> dict:
        """仅供运行时源: 只返回已通过且可见的媒体"""
        with _session(db) as _db:
            media = curd_curated_media.getVisibleById(_db, local_id)
            if not media:
                return {}
            media['episodes'] = curd_curated_episode.getByMediaId(_db, local_id)
            return media


curated_service = CuratedService()
