import unittest

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from app.models.facilities import EquipmentUnit
from app.models.memberships import MembershipPlan


class CaseInsensitiveIndexTests(unittest.TestCase):
    def test_indexes_lower_the_name_column_not_a_string_literal(self) -> None:
        indexes = (
            next(index for index in MembershipPlan.__table__.indexes if index.unique),
            next(index for index in EquipmentUnit.__table__.indexes if index.unique),
        )

        for index in indexes:
            with self.subTest(index=index.name):
                statement = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
                self.assertIn("lower(name)", statement)
                self.assertNotIn("lower('name')", statement)


if __name__ == "__main__":
    unittest.main()
