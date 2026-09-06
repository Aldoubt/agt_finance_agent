from core.generators.archive_consistency_checker import ArchiveConsistencyChecker


class DummyInvoice:
    total = 10


class DummyGraph:
    total_amount = 10
    invoices = [DummyInvoice()]
    items = []


def test_consistency_amount_pass():
    assert ArchiveConsistencyChecker().check(DummyGraph())["valid"] is True
