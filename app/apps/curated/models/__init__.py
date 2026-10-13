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


# 智能归类的初始配置: 仅当「分类管理」尚未配置时写入一次, 之后完全由后台维护
_CLASSIFY_SEED = [
    ('语文', 1,
     r'(?<!双)语文|大语文|国学|唐诗|宋词|古诗|汉字|拼音|成语|三字经|弟子规|千字文|三十六计|文言文|跟着书本去旅行'),
    ('数学', 2, r'数学|数字积木|奥数|几何|算术|数理'),
    ('艺术', 3, r'写字|书法|美术|绘画|声乐|钢琴|乐器|舞蹈|武术'),
    ('儿童科普纪录片', 4,
     r'纪录片|科普|百科|国家地理|National Geographic|微观小世界|小小世界|神奇校车|昆虫|恐龙|STEM|大自然|自然界'),
    ('英语', 5,
     r'英语|英文|英文字幕|双语|双字幕|美语|美音|口语|听力|音标|自然拼读|单词|词汇|磨耳朵|'
     r'新概念|走遍美国|雅思|托福|English|Phonics|字母积木|分级阅读|绘本|播客|Podcast'),
    ('奥斯卡奖&经典动画', 6, r'奥斯卡|动画短片|经典动画'),
]
_CLASSIFY_DEFAULT_NAME = '英语'


def _seed_classify_defaults() -> None:
    """首次为「分类管理」补齐智能归类的关键词/排序/兜底分类。

    - 仅在字段为空时写入, 绝不覆盖用户已配置的值;
    - 仅当所有分类的 order_num 完全相同时(即尚未手动排序)才自动分配优先级;
    - 之后规则完全由「分类管理」维护, 启动不再改动。
    """
    db = None
    try:
        from db.session import SessionLocal
        db = SessionLocal()
        cats = db.query(CuratedCategory).filter(CuratedCategory.is_deleted == 0).all()
        if not cats:
            return
        by_name = {c.name: c for c in cats}
        all_same_order = len({(c.order_num or 0) for c in cats}) <= 1
        changed = False
        for name, order, keywords in _CLASSIFY_SEED:
            c = by_name.get(name)
            if c is None:
                continue
            if not (c.keywords or '').strip():
                c.keywords = keywords
                changed = True
            if all_same_order and (c.order_num or 0) != order:
                c.order_num = order
                changed = True
        if not any((c.is_default or 0) == 1 for c in cats):
            (by_name.get(_CLASSIFY_DEFAULT_NAME) or cats[0]).is_default = 1
            changed = True
        if changed:
            db.commit()
            logger.info('[curated] 已初始化智能归类关键词/排序/兜底分类')
    except Exception as e:  # noqa
        if db is not None:
            db.rollback()
        logger.warning(f'[curated] 初始化智能归类默认值失败(忽略): {e}')
    finally:
        if db is not None:
            db.close()


_seed_classify_defaults()


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
