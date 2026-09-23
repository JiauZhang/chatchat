"""A cron schedule has to mean the same thing to us as it does to cron."""
from datetime import datetime

from chatchat.core.cron import (human, next_run, parse)


def test_five_fields_are_the_only_shape_accepted():
    assert parse('* * * * *') is not None
    assert parse('* * * *') is None
    assert parse('* * * * * *') is None


def test_a_field_accepts_a_star_a_number_a_range_and_a_step():
    fields = parse('0,30 9-17/4 1-5 1,12 *')
    assert fields['minute'] == [0, 30]
    assert fields['hour'] == [9, 13, 17]
    assert fields['day_of_month'] == [1, 2, 3, 4, 5]
    assert fields['month'] == [1, 12]
    assert fields['day_of_week'] == list(range(7))


def test_a_value_outside_its_field_is_refused():
    assert parse('60 * * * *') is None
    assert parse('* 24 * * *') is None
    assert parse('* * 0 * *') is None
    assert parse('* * * 13 *') is None
    assert parse('5-1 * * * *') is None


def test_seven_is_sunday_whatever_way_it_is_written():
    assert parse('* * * * 7')['day_of_week'] == [0]
    assert parse('* * * * 5-7')['day_of_week'] == [0, 5, 6]


def test_the_next_run_is_strictly_after_the_given_minute():
    fields = parse('30 14 * * *')
    assert next_run(fields, datetime(2026, 5, 1, 14, 30)) == datetime(
        2026, 5, 2, 14, 30)
    assert next_run(fields, datetime(2026, 5, 1, 9, 0)) == datetime(
        2026, 5, 1, 14, 30)


def test_a_step_over_days_lands_on_the_next_matching_date():
    fields = parse('0 8 * * 1')
    assert next_run(fields, datetime(2026, 5, 1, 12, 0)) == datetime(
        2026, 5, 4, 8, 0)


def test_a_day_pinned_both_ways_matches_either_day():
    fields = parse('0 0 13 * 5')
    matches = []
    when = datetime(2026, 2, 1)
    while len(matches) < 3:
        when = next_run(fields, when)
        matches.append(when)
    assert [m.strftime('%a %d %b') for m in matches] == [
        'Fri 06 Feb', 'Fri 13 Feb', 'Fri 20 Feb']


def test_a_schedule_that_never_matches_gives_nothing():
    assert parse('0 0 30 2 *') is not None
    assert next_run(parse('0 0 30 2 *'), datetime(2026, 1, 1)) is None


def test_a_schedule_reads_back_in_words():
    assert human('*/5 * * * *') == 'every 5 minutes'
    assert human('30 14 * * *') == 'every day at 14:30'
    assert human('0 9 * * 1') == 'every Mon at 09:00'
    assert human('0 0 1 1 *') == 'every year on Jan 1 at 00:00'
