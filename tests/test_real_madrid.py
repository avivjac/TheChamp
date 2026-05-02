"""
Tests for real_madrid.py
Run with:  python -m pytest tests/test_real_madrid.py -v
       or: python tests/test_real_madrid.py

Unit tests:        fast, no network, use fake data
Integration tests: hit the real RapidAPI and Google Calendar API
"""

import sys
import os
import datetime
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

import real_madrid


# ── Unit tests — no network calls ─────────────────────────────────────────────

class TestIsFirstTeam(unittest.TestCase):

    def test_rm_home_lala(self):
        m = {"homeTeamId": "8633", "awayTeamId": "8558", "leagueId": 87}
        self.assertTrue(real_madrid._is_first_team(m))

    def test_rm_away_laliga(self):
        m = {"homeTeamId": "8634", "awayTeamId": "8633", "leagueId": 87}
        self.assertTrue(real_madrid._is_first_team(m))

    def test_rm_champions_league(self):
        m = {"homeTeamId": "8633", "awayTeamId": "9823", "leagueId": 42}
        self.assertTrue(real_madrid._is_first_team(m))

    def test_rm_wrong_league_excluded(self):
        # Copa del Rey, Liga F, youth — not in RM_LEAGUE_IDS
        for league_id in [9907, 9741, 9375, 8968, 9138, 999]:
            m = {"homeTeamId": "8633", "awayTeamId": "8558", "leagueId": league_id}
            self.assertFalse(real_madrid._is_first_team(m),
                             f"league {league_id} should be excluded")

    def test_castilla_excluded(self):
        # Real Madrid Castilla has a different team ID
        m = {"homeTeamId": "8367", "awayTeamId": "8558", "leagueId": 87}
        self.assertFalse(real_madrid._is_first_team(m))

    def test_rm_women_excluded(self):
        m = {"homeTeamId": "1077486", "awayTeamId": "8558", "leagueId": 9907}
        self.assertFalse(real_madrid._is_first_team(m))

    def test_neither_team_rm(self):
        m = {"homeTeamId": "8634", "awayTeamId": "8558", "leagueId": 87}
        self.assertFalse(real_madrid._is_first_team(m))


class TestParseEventDt(unittest.TestCase):

    def test_datetime_string(self):
        dt = real_madrid._parse_event_dt("2026-05-03T21:00:00+02:00")
        self.assertIsInstance(dt, datetime.datetime)
        self.assertEqual(dt.tzinfo, datetime.timezone.utc)
        self.assertEqual(dt.hour, 19)   # 21:00+02:00 == 19:00 UTC

    def test_date_only_string_defaults_to_2000_utc(self):
        dt = real_madrid._parse_event_dt("2026-05-03")
        self.assertIsInstance(dt, datetime.datetime)
        self.assertEqual(dt.hour, 20)   # placeholder 20:00 UTC


class TestFormatters(unittest.TestCase):

    def _match(self, started=False, finished=False, score="1 - 0"):
        status = {"started": started, "finished": finished}
        if started:
            status["scoreStr"] = score
        return {
            "homeTeamId": "8633",   # Real Madrid first-team ID
            "awayTeamId": "8634",   # Barcelona
            "leagueId": 87,         # LaLiga
            "homeTeamName": "Real Madrid",
            "awayTeamName": "Barcelona",
            "leagueName": "LaLiga",
            "homeTeamScore": 1,
            "awayTeamScore": 0,
            "status": status,
            "matchDate": "2026-05-03T19:00:00Z",
        }

    def test_prematch_contains_teams_and_league(self):
        kickoff = datetime.datetime(2026, 5, 3, 19, 0, tzinfo=datetime.timezone.utc)
        msg = real_madrid.format_prematch_msg(self._match(), kickoff)
        self.assertIn("Real Madrid", msg)
        self.assertIn("Barcelona", msg)
        self.assertIn("LaLiga", msg)
        self.assertIn("45", msg)

    def test_live_msg_shows_score(self):
        msg = real_madrid.format_live_msg(self._match(started=True, score="2 - 1"))
        self.assertIn("Real Madrid", msg)
        self.assertIn("Barcelona", msg)
        self.assertIn("2 - 1", msg)
        self.assertIn("50", msg)

    def test_live_msg_fallback_when_no_score_str(self):
        m = self._match(started=True)
        del m["status"]["scoreStr"]
        msg = real_madrid.format_live_msg(m)
        # Should still produce a readable message
        self.assertIn("Real Madrid", msg)
        self.assertIn("Barcelona", msg)

    def test_final_msg_shows_score_and_ft(self):
        msg = real_madrid.format_final_msg(
            self._match(started=True, finished=True, score="3 - 0")
        )
        self.assertIn("Real Madrid", msg)
        self.assertIn("3 - 0", msg)
        self.assertIn("Full Time", msg)
        self.assertIn("LaLiga", msg)

    def test_get_real_madrid_updates_finished_match(self):
        """Verify get_real_madrid_updates formats a finished match correctly."""
        finished = self._match(started=True, finished=True, score="2 - 1")
        finished["status"]["reason"] = {"short": "FT", "longKey": "finished"}
        finished["matchDate"] = "2026-04-20T19:00:00Z"
        # Patch _search_matches to return our fixture
        original = real_madrid._search_matches
        real_madrid._search_matches = lambda: [finished]
        try:
            result = real_madrid.get_real_madrid_updates()
            self.assertIn("Real Madrid", result)
            self.assertIn("2 - 1", result)
            self.assertIn("FT", result)
        finally:
            real_madrid._search_matches = original

    def test_get_real_madrid_updates_upcoming_match(self):
        upcoming = self._match(started=False, finished=False)
        upcoming["matchDate"] = "2026-05-10T19:00:00Z"
        original = real_madrid._search_matches
        real_madrid._search_matches = lambda: [upcoming]
        try:
            result = real_madrid.get_real_madrid_updates()
            self.assertIn("vs", result)
            self.assertNotIn("LIVE", result)
            self.assertNotIn("FT", result)
        finally:
            real_madrid._search_matches = original

    def test_get_real_madrid_updates_empty(self):
        original = real_madrid._search_matches
        real_madrid._search_matches = lambda: []
        try:
            result = real_madrid.get_real_madrid_updates()
            self.assertIn("No Real Madrid", result)
        finally:
            real_madrid._search_matches = original


# ── Integration tests — real API calls ────────────────────────────────────────

class TestApiIntegration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.environ.get("FOOTBALL_API_KEY"):
            raise unittest.SkipTest("FOOTBALL_API_KEY not set — skipping API tests")
        # Fetch once; reuse across all test methods to save API calls
        cls.matches = real_madrid._search_matches()

    def test_search_returns_non_empty_list(self):
        self.assertIsInstance(self.matches, list)
        self.assertGreater(len(self.matches), 0)

    def test_each_match_has_required_fields(self):
        required = {"id", "matchDate", "homeTeamName", "awayTeamName", "status", "leagueId"}
        for m in self.matches:
            missing = required - m.keys()
            self.assertEqual(missing, set(), f"Match {m.get('id')} missing fields: {missing}")

    def test_match_dates_are_valid_iso(self):
        for m in self.matches:
            date_str = m.get("matchDate", "")
            try:
                datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except ValueError:
                self.fail(f"Invalid matchDate '{date_str}' in match {m.get('id')}")

    def test_real_madrid_team_id_present_in_results(self):
        ids = {m.get("homeTeamId") for m in self.matches} | {m.get("awayTeamId") for m in self.matches}
        self.assertIn(real_madrid.REAL_MADRID_TEAM_ID, ids,
                      "Team ID 8633 (Real Madrid) should appear in search results")

    def test_first_team_filter_returns_only_rm_first_team(self):
        first_team = [m for m in self.matches if real_madrid._is_first_team(m)]
        self.assertGreater(len(first_team), 0, "Expected at least one first-team match")
        for m in first_team:
            self.assertIn(m["leagueId"], real_madrid.RM_LEAGUE_IDS,
                          f"Match {m['id']} in unexpected league {m['leagueId']}")
            is_rm = (
                m.get("homeTeamId") == real_madrid.REAL_MADRID_TEAM_ID
                or m.get("awayTeamId") == real_madrid.REAL_MADRID_TEAM_ID
            )
            self.assertTrue(is_rm, f"Match {m['id']} does not involve Real Madrid")

    def test_get_match_by_known_id(self):
        known_id = str(self.matches[0]["id"])
        result = real_madrid.get_match_by_id(known_id)
        self.assertIsNotNone(result)
        self.assertEqual(str(result["id"]), known_id)

    def test_get_match_by_fake_id_returns_none(self):
        result = real_madrid.get_match_by_id("000000000")
        self.assertIsNone(result)

    def test_get_real_madrid_updates_format(self):
        result = real_madrid.get_real_madrid_updates()
        self.assertIsInstance(result, str)
        lines = result.strip().split("\n")
        self.assertTrue(lines[0].startswith("⚽"),
                        f"Header should start with ⚽, got: {lines[0]!r}")
        self.assertGreater(len(lines), 1, "Expected header + at least one match line")

    def test_get_real_madrid_updates_max_8_matches(self):
        result = real_madrid.get_real_madrid_updates()
        match_lines = [l for l in result.split("\n") if l.strip() and not l.startswith("⚽")]
        self.assertLessEqual(len(match_lines), 8)

    def test_todays_match_is_none_or_valid_dict(self):
        result = real_madrid.get_todays_match_from_api()
        if result is None:
            return  # no game today — fine
        self.assertIn("id", result)
        self.assertIn("homeTeamName", result)
        self.assertTrue(real_madrid._is_first_team(result),
                        "Today's match should pass the first-team filter")


# ── Integration tests — Google Calendar API ───────────────────────────────────

class TestRmCalendarIntegration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.exists("token.json") and not os.path.exists("credentials.json"):
            raise unittest.SkipTest("Google credentials not found — skipping calendar tests")

    def test_find_rm_calendar_id_returns_string(self):
        cal_id = real_madrid._find_rm_calendar_id()
        self.assertIsNotNone(cal_id, "Expected to find a calendar named 'Real Madrid'")
        self.assertIsInstance(cal_id, str)
        self.assertNotEqual(cal_id, "primary")
        print(f"\n  'Real Madrid' calendar ID: {cal_id}")

    def test_get_upcoming_games_returns_list(self):
        games = real_madrid.get_upcoming_games_from_rm_calendar(days=60)
        self.assertIsInstance(games, list)
        print(f"\n  Upcoming games found: {len(games)}")

    def test_upcoming_games_have_required_fields(self):
        games = real_madrid.get_upcoming_games_from_rm_calendar(days=60)
        for g in games:
            self.assertIn("title", g, "Each game should have a 'title' field")
            self.assertIn("kickoff_utc", g, "Each game should have a 'kickoff_utc' field")
            self.assertIn("kickoff_local", g, "Each game should have a 'kickoff_local' field")
            self.assertIsInstance(g["kickoff_utc"], datetime.datetime)
            self.assertIsInstance(g["kickoff_local"], str)

    def test_upcoming_games_are_in_future(self):
        games = real_madrid.get_upcoming_games_from_rm_calendar(days=60)
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        for g in games:
            self.assertGreaterEqual(g["kickoff_utc"], now,
                                    f"Game '{g['title']}' at {g['kickoff_utc']} is in the past")

    def test_upcoming_games_print_schedule(self):
        games = real_madrid.get_upcoming_games_from_rm_calendar(days=90)
        print(f"\n  --- Upcoming Real Madrid schedule ({len(games)} games) ---")
        for g in games:
            print(f"  {g['kickoff_utc'].strftime('%Y-%m-%d')}  {g['kickoff_local']}  {g['title']}")

    def test_todays_game_is_none_or_valid_tuple(self):
        result = real_madrid.get_todays_game_from_rm_calendar()
        if result is None:
            print("\n  No Real Madrid game today in RM calendar")
            return
        kickoff, title = result
        self.assertIsInstance(kickoff, datetime.datetime)
        self.assertIsInstance(title, str)
        print(f"\n  Today's game: '{title}' at {kickoff.strftime('%H:%M')} UTC")


if __name__ == "__main__":
    unittest.main(verbosity=2)
