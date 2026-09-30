#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : curd_provider.py
from sqlalchemy.orm import Session

from common.curd_base import CRUDBase
from ..models.curated_provider import CuratedProvider


class CURDCuratedProvider(CRUDBase):
    def getByCode(self, db: Session, code: str, only_enabled: bool = False):
        filters = [self.model.code == code]
        if only_enabled:
            filters.append(self.model.status == 1)
        obj = db.query(*self.query_columns).filter(*filters, self.model.is_deleted == 0).first()
        return dict(obj or {})

    def getEnabledProviders(self, db: Session):
        objs = db.query(*self.query_columns).filter(
            self.model.status == 1, self.model.is_deleted == 0
        ).order_by(self.model.order_num).all()
        return [dict(o) for o in objs]


curd_curated_provider = CURDCuratedProvider(CuratedProvider)
