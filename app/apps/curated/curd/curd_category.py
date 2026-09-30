#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File  : curd_category.py
from sqlalchemy.orm import Session

from common.curd_base import CRUDBase
from ..models.curated_category import CuratedCategory


class CURDCuratedCategory(CRUDBase):
    def getEnabledCategories(self, db: Session):
        objs = db.query(*self.query_columns).filter(
            self.model.status == 1, self.model.is_deleted == 0
        ).order_by(self.model.order_num).all()
        return [dict(o) for o in objs]


curd_curated_category = CURDCuratedCategory(CuratedCategory)
