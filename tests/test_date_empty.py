"""Empty OrgDate must stringify, not raise.

A node with no SCHEDULED/DEADLINE returns the OrgDate(None) sentinel. It is
correctly falsy, but str() used to raise AttributeError from date_time_format,
so f"{node.scheduled}" crashed on every undated node. Found 2026-08-10 while
listing billing tasks across nine spaces.
"""
from org_workspace._vendor.orgparse.date import OrgDate


def test_empty_orgdate_is_falsy():
    assert not OrgDate(None)


def test_empty_orgdate_str_is_empty_not_raise():
    assert str(OrgDate(None)) == ""


def test_empty_orgdate_fstring_does_not_raise():
    assert f"sched={OrgDate(None)}" == "sched="


def test_real_date_still_formats():
    import datetime
    assert str(OrgDate(datetime.date(2026, 8, 10))) == "<2026-08-10 Mon>"
