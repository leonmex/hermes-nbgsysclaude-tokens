import re


def test_registers_exactly_one_profile_when_anthropic_present(load_plugin):
    pkg = load_plugin()
    assert len(pkg.registered) == 1
    assert pkg.registered[0].name == "nbgsysclaude-tokens"


def test_stays_inert_without_anthropic(load_plugin, caplog):
    with caplog.at_level("WARNING"):
        pkg = load_plugin(with_anthropic=False)
    assert pkg.registered == [] and pkg.PROFILE is None
    assert any("inactive" in r.getMessage() for r in caplog.records)


def test_never_registers_over_the_bundled_names(load_plugin):
    names = {p.name for p in load_plugin().registered}
    assert names.isdisjoint({"anthropic", "claude", "claude-code"})


def test_redaction_pattern_matches_tokens_only(load_plugin):
    pkg = load_plugin()
    assert len(pkg.redaction) == 1
    pattern = re.compile(pkg.redaction[0])
    assert pattern.search("x sk-ant-oat01-" + "A" * 40)
    assert not pattern.search("sk-ant-api03-" + "A" * 40)


def test_registration_failure_is_contained(load_plugin):
    def explode(profile):
        raise RuntimeError("registry broken")

    pkg = load_plugin(register=explode)  # must not raise
    assert pkg.PROFILE is None
