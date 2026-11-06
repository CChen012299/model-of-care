"""Clinical rules engine.

The engine core (domain, conditions, needs, evaluator) is pure Python with no
database or web dependencies: given a PatientContext, the rule catalog and an
as-of date, it returns enrollments, needs and draft tasks. runner.py is the
only module that touches the database.
"""
