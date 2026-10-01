import pytest

from signalwalk.config import ConfigError, load_dotenv, load_settings, parse_dotenv


def test_default_config_loads(settings):
    t = settings.thresholds
    assert t.dead_dbm < t.weak_dbm < t.strong_dbm < 0
    assert settings.model.prior.wall_db["heavy"] > settings.model.prior.wall_db["light"]


def test_env_overrides():
    s = load_settings(environ={"SIGNALWALK_PORT": "9001", "SIGNALWALK_MODE": "real", "SIGNALWALK_SIM_SEED": "9"})
    assert (s.server.port, s.server.mode, s.server.sim_seed) == (9001, "real", 9)


@pytest.mark.parametrize("env", [{"SIGNALWALK_MODE": "nope"}, {"SIGNALWALK_PORT": "abc"}, {"SIGNALWALK_PORT": "70000"}])
def test_bad_env_rejected(env):
    with pytest.raises(ConfigError):
        load_settings(environ=env)


def test_unknown_keys_and_bad_thresholds_rejected(tmp_path):
    bad = tmp_path / "c.yaml"
    bad.write_text("thresholds: {strong_dbm: -55, weak_dbm: -60, dead_dbm: -50}\n")
    with pytest.raises(ConfigError, match="thresholds"):
        load_settings(bad)
    bad.write_text("colour: red\n")
    with pytest.raises(ConfigError, match="Unknown top-level"):
        load_settings(bad)
    bad.write_text("gp: {sigma_x: 1}\n")
    with pytest.raises(ConfigError, match="Unknown key"):
        load_settings(bad)


def test_missing_explicit_file():
    with pytest.raises(ConfigError, match="not found"):
        load_settings("/no/such/config.yaml")


def test_dotenv_parsing_and_no_override(tmp_path):
    assert parse_dotenv("# c\nA=1\nB = 'two words'\nC=x # note\nbad\n") == {"A": "1", "B": "two words", "C": "x"}
    f = tmp_path / ".env"
    f.write_text("A=file\nB=new\n")
    env = {"A": "set"}
    assert load_dotenv(f, env) and env == {"A": "set", "B": "new"}
    assert not load_dotenv(tmp_path / "none", env)
