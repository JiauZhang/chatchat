from chatchat.runtime.markdown import parse_frontmatter


def test_a_wellformed_block_parses_and_leaves_the_body():
    meta, body = parse_frontmatter("---\nname: reviewer\ntools: [Read, Write]\n---\n\nbe harsh\n")
    assert meta == {"name": "reviewer", "tools": ["Read", "Write"]}
    assert body == "be harsh"


def test_a_block_missing_entirely_returns_the_text_unchanged():
    meta, body = parse_frontmatter("just a body\n")
    assert meta == {}
    assert body == "just a body\n"


def test_a_value_with_a_colon_is_repaired_by_quoting():
    meta, body = parse_frontmatter("---\ndescription: reads diffs: fast and thorough\n---\n\nbody\n")
    assert meta == {"description": "reads diffs: fast and thorough"}
    assert body == "body"


def test_times_and_urls_stay_unquoted_and_intact():
    meta, _ = parse_frontmatter("---\nat: 12:34\nhome: https://example.com/x\n---\n\nbody\n")
    assert meta == {"at": "12:34", "home": "https://example.com/x"}


def test_an_unquoted_glob_is_repaired_not_dropped():
    meta, _ = parse_frontmatter("---\npaths: **/*.py\n---\n\nbody\n")
    assert meta == {"paths": "**/*.py"}


def test_an_unrecoverable_block_is_none_so_the_caller_can_report_it():
    meta, body = parse_frontmatter('---\nname: "unclosed quote\n---\n\nbody\n')
    assert meta is None
    assert body == "body"
