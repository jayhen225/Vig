-- Each row = one team's DEFENSIVE perspective on one game.
-- Target: def_epa (EPA allowed by this team's defense — lower = better defense)
-- Features: team's own rolling defensive stats + opponent's rolling offensive stats
-- Same leakage-free structure as the offense query: rolling windows use only PRIOR games.

WITH team_defense AS (
    SELECT
        defteam AS team,
        season,
        week,
        game_id,
        COUNT(*) AS def_plays,
        ROUND(AVG(epa), 4) AS def_epa,
        ROUND(AVG(CASE WHEN play_type = 'pass' THEN epa END), 4) AS def_pass_epa,
        ROUND(AVG(CASE WHEN play_type = 'run' THEN epa END), 4) AS def_rush_epa
    FROM pbp_data
    WHERE play_type IN ('pass', 'run') AND defteam IS NOT NULL
    GROUP BY defteam, season, week, game_id
),
opp_offense AS (
    SELECT
        posteam AS team,
        season,
        week,
        game_id,
        ROUND(AVG(epa), 4) AS off_epa,
        ROUND(AVG(CASE WHEN play_type = 'pass' THEN epa END), 4) AS off_pass_epa,
        ROUND(AVG(CASE WHEN play_type = 'run' THEN epa END), 4) AS off_rush_epa,
        ROUND(SUM(CASE WHEN play_type = 'pass' THEN 1 ELSE 0 END) * 1.0 / COUNT(*), 4) AS pass_rate
    FROM pbp_data
    WHERE play_type IN ('pass', 'run') AND posteam IS NOT NULL
    GROUP BY posteam, season, week, game_id
),
game_scores AS (
    SELECT game_id, home_team, away_team, home_score, away_score
    FROM schedule_data
),
combined AS (
    SELECT
        d.team,
        d.season,
        d.week,
        d.game_id,
        d.def_plays,
        d.def_epa,
        d.def_pass_epa,
        d.def_rush_epa,
        o_opp.off_epa AS opp_off_epa,
        o_opp.off_pass_epa AS opp_off_pass_epa,
        o_opp.off_rush_epa AS opp_off_rush_epa,
        o_opp.pass_rate AS opp_pass_rate,
        CASE WHEN g.home_team = d.team THEN 1 ELSE 0 END AS is_home,
        CASE WHEN g.home_team = d.team THEN g.home_score ELSE g.away_score END AS points_scored,
        CASE WHEN g.home_team = d.team THEN g.away_score ELSE g.home_score END AS points_allowed
    FROM team_defense d
    JOIN opp_offense o_opp
        ON d.game_id = o_opp.game_id AND d.team != o_opp.team
    JOIN game_scores g
        ON d.game_id = g.game_id
),
league_averages AS (
    SELECT
        ROUND(AVG(def_epa), 4) AS league_def_epa,
        ROUND(AVG(def_pass_epa), 4) AS league_def_pass_epa,
        ROUND(AVG(def_rush_epa), 4) AS league_def_rush_epa,
        ROUND(AVG(opp_off_epa), 4) AS league_opp_off_epa,
        ROUND(AVG(opp_off_pass_epa), 4) AS league_opp_off_pass_epa,
        ROUND(AVG(opp_off_rush_epa), 4) AS league_opp_off_rush_epa,
        ROUND(AVG(opp_pass_rate), 4) AS league_opp_pass_rate
    FROM combined
)
SELECT
    c.team,
    c.season,
    c.week,
    c.game_id,
    c.is_home,
    c.points_scored,
    c.points_allowed,
    c.def_epa,
    c.def_pass_epa,
    c.def_rush_epa,
    COALESCE(
        ROUND(AVG(c.def_epa) OVER (PARTITION BY c.team, c.season ORDER BY c.week ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 4),
        la.league_def_epa
    ) AS rolling_def_epa,
    COALESCE(
        ROUND(AVG(c.def_pass_epa) OVER (PARTITION BY c.team, c.season ORDER BY c.week ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 4),
        la.league_def_pass_epa
    ) AS rolling_def_pass_epa,
    COALESCE(
        ROUND(AVG(c.def_rush_epa) OVER (PARTITION BY c.team, c.season ORDER BY c.week ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 4),
        la.league_def_rush_epa
    ) AS rolling_def_rush_epa,
    COALESCE(
        ROUND(AVG(c.opp_off_epa) OVER (PARTITION BY c.team, c.season ORDER BY c.week ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 4),
        la.league_opp_off_epa
    ) AS rolling_opp_off_epa,
    COALESCE(
        ROUND(AVG(c.opp_off_pass_epa) OVER (PARTITION BY c.team, c.season ORDER BY c.week ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 4),
        la.league_opp_off_pass_epa
    ) AS rolling_opp_off_pass_epa,
    COALESCE(
        ROUND(AVG(c.opp_off_rush_epa) OVER (PARTITION BY c.team, c.season ORDER BY c.week ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 4),
        la.league_opp_off_rush_epa
    ) AS rolling_opp_off_rush_epa,
    COALESCE(
        ROUND(AVG(c.opp_pass_rate) OVER (PARTITION BY c.team, c.season ORDER BY c.week ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 4),
        la.league_opp_pass_rate
    ) AS rolling_opp_pass_rate
FROM combined c
CROSS JOIN league_averages la
ORDER BY c.season, c.week, c.team