from core.logger import logger
from db.base_class import Base
from db.session import engine
from .curated_provider import CuratedProvider
from .curated_category import CuratedCategory
from .curated_media import CuratedMedia, UNIQUE_NAME
from .curated_episode import CuratedEpisode

__all__ = ['CuratedProvider', 'CuratedCategory', 'CuratedMedia', 'CuratedEpisode']

Base.metadata.create_all(engine)


def _auto_add_columns() -> None:
    """为已存在的旧表补齐新增字段(create_all 不会修改已存在的表)。

    仅做增量 ALTER TABLE ADD COLUMN, 失败时静默忽略, 不影响启动。
    """
    try:
        from sqlalchemy import inspect, text
        from sqlalchemy.schema import CreateColumn
    except Exception:  # noqa
        return
    try:
        insp = inspect(engine)
    except Exception:  # noqa
        return
    for model in (CuratedProvider, CuratedCategory, CuratedMedia, CuratedEpisode):
        table = model.__table__
        try:
            if not insp.has_table(table.name):
                continue
            exists = {c['name'] for c in insp.get_columns(table.name)}
            for column in table.columns:
                if column.name in exists:
                    continue
                ddl = str(CreateColumn(column).compile(dialect=engine.dialect))
                with engine.begin() as conn:
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {ddl}'))
        except Exception:  # noqa
            continue


_auto_add_columns()


def _ensure_unique_index() -> None:
    """为 curated_media 建立 (provider_code, media_id) 唯一索引(数据库层硬约束)。

    - 旧库可能已有重复行: 先按“活跃优先, 其次 id 最小”保留一条, 其余物理删除(含其选集);
    - 索引已存在 / 字段缺失时跳过;
    - 任何异常均不影响启动(数据库不支持时由应用层去重兜底)。
    """
    try:
        from sqlalchemy import inspect, text
    except Exception:  # noqa
        return
    try:
        insp = inspect(engine)
        table = CuratedMedia.__table__
        if not insp.has_table(table.name):
            return
        cols = {c['name'] for c in insp.get_columns(table.name)}
        if not {'provider_code', 'media_id'} <= cols:
            return
        # 已存在同列组合的唯一索引/约束 -> 幂等跳过
        # (注: SQLite 下 UNIQUE 约束不会出现在 get_indexes, 而在 get_unique_constraints)
        want = ['provider_code', 'media_id']
        for idx in insp.get_indexes(table.name):
            if idx.get('unique') and [c for c in (idx.get('column_names') or [])] == want:
                return
        for uc in insp.get_unique_constraints(table.name):
            if [c for c in (uc.get('column_names') or [])] == want:
                return
        with engine.begin() as conn:
            media_tbl = table.name
            ep_tbl = CuratedEpisode.__tablename__
            # 1) 去重: 找出每条 (provider_code, media_id) 中“较差”的行并物理删除
            dup_rows = conn.execute(text(
                f"SELECT id FROM {media_tbl} m WHERE EXISTS ("
                f"  SELECT 1 FROM {media_tbl} x"
                "  WHERE x.provider_code = m.provider_code AND x.media_id = m.media_id"
                "    AND (COALESCE(x.is_deleted,0) < COALESCE(m.is_deleted,0)"
                "         OR (COALESCE(x.is_deleted,0) = COALESCE(m.is_deleted,0) AND x.id < m.id)))"
            )).fetchall()
            dup_ids = [int(r[0]) for r in dup_rows]
            if dup_ids:
                id_csv = ','.join(str(i) for i in dup_ids)
                conn.execute(text(f"DELETE FROM {ep_tbl} WHERE media_id IN ({id_csv})"))
                conn.execute(text(f"DELETE FROM {media_tbl} WHERE id IN ({id_csv})"))
                logger.warning(f'[curated] 已清理重复媒体 {len(dup_ids)} 条, 以保证唯一约束')
            # 2) 建唯一索引(MySQL 不支持 CREATE INDEX IF NOT EXISTS, 前面已做过存在性检查)
            ine = 'IF NOT EXISTS ' if engine.dialect.name in ('sqlite', 'postgresql') else ''
            conn.execute(text(
                f"CREATE UNIQUE INDEX {ine}{UNIQUE_NAME} "
                f"ON {media_tbl} (provider_code, media_id)"
            ))
            logger.info(f'[curated] 已建立唯一索引 {UNIQUE_NAME}(provider_code, media_id)')
    except Exception as e:  # noqa
        logger.warning(f'[curated] 建立唯一索引失败(将由应用层去重兜底): {e}')


_ensure_unique_index()
