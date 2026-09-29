import json
import subprocess
import sys
import time

import pytest

from schema_lint.cli import main
from schema_lint.lint import USER_AGENT

GOOD = """<html><head><script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Organization", "name": "Example Co",
 "url": "https://example.com/", "logo": "https://example.com/logo.png", "sameAs": ["https://example.org/co"],
 "description": "Widgets", "telephone": "+1-506-555-0100", "email": "hello@example.com",
 "address": {"@type": "PostalAddress", "streetAddress": "1 Main St", "addressLocality": "Exampleville",
             "addressRegion": "NB", "postalCode": "E1V 0A0", "addressCountry": "CA"}}
</script></head><body>hello</body></html>"""
BAD = GOOD.replace('"name"', '"nmae"', 1)
WARN = GOOD.replace('"telephone": "+1-506-555-0100", ', "")


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_clean_file_exits_0(tmp_path, capsys):
    assert main([write(tmp_path, "good.html", GOOD)]) == 0
    out = capsys.readouterr().out
    assert "1 item(s) (1 json-ld): Organization" in out and "0 error(s), 0 warning(s), 0 info" in out


def test_findings_exit_1_and_fail_on(tmp_path, capsys):
    bad = write(tmp_path, "bad.html", BAD)
    assert main([bad]) == 1
    assert "did you mean 'name'?" in capsys.readouterr().out
    warn = write(tmp_path, "warn.html", WARN)
    assert main([warn]) == 0
    assert main([warn, "--fail-on", "warning"]) == 1
    assert main([bad, "--fail-on", "never"]) == 0


def test_usage_errors_exit_2(tmp_path, capsys):
    assert main([str(tmp_path / "missing.html")]) == 2
    assert main(["https://example.com/", "--max-pages", "31"]) == 2
    assert main(["https://example.com/", "--delay", "0.5"]) == 2
    with pytest.raises(SystemExit) as e:
        main(["--format", "xml", "x.html"])
    assert e.value.code == 2


def test_network_error_exits_2(unused_port, capsys):
    assert main([f"http://127.0.0.1:{unused_port}/"]) == 2
    assert "schema-lint:" in capsys.readouterr().err


def test_directory_and_jsonld_files(tmp_path, capsys):
    (tmp_path / "site").mkdir()
    write(tmp_path / "site", "a.html", GOOD)
    write(tmp_path / "site", "b.jsonld", '{"@context": "https://schema.org",\n "@type": "Thing",\n "nmae": 1}')
    assert main([str(tmp_path / "site"), "--format", "json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert [p["url"].rsplit("/", 1)[1] for p in data["pages"]] == ["a.html", "b.jsonld"]
    [finding] = data["pages"][1]["findings"]
    assert finding["code"] == "unknown-property" and finding["line"] == 1
    assert data["summary"]["error"] == 1 and data["summary"]["items"] == 2


def test_json_syntax_error_line_in_jsonld_file(tmp_path, capsys):
    f = write(tmp_path, "x.jsonld", '{\n  "@context": "https://schema.org",\n  "name": "x",\n}')
    assert main([f, "--format", "json"]) == 1
    [finding] = json.loads(capsys.readouterr().out)["pages"][0]["findings"]
    assert finding["code"] == "json-syntax" and finding["line"] == 4


def test_sarif_output(tmp_path, capsys):
    out = tmp_path / "report.sarif"
    assert main([write(tmp_path, "bad.html", BAD), "--format", "sarif", "-o", str(out)]) == 1
    sarif = json.loads(out.read_text(encoding="utf-8"))
    assert sarif["version"] == "2.1.0" and sarif["$schema"].endswith("sarif-2.1.0.json")
    run = sarif["runs"][0]
    assert run["tool"]["driver"]["name"] == "schema-lint"
    rule_ids = [r["id"] for r in run["tool"]["driver"]["rules"]]
    for res in run["results"]:
        assert res["level"] in ("error", "warning", "note")
        assert rule_ids[res["ruleIndex"]] == res["ruleId"]
        assert res["locations"][0]["physicalLocation"]["artifactLocation"]["uri"].endswith("bad.html")
    assert {"unknown-property", "google-recommended"} <= set(rule_ids)
    assert "error(s)" in capsys.readouterr().err


def test_url_mode_sends_user_agent(site, capsys):
    s = site({"/": (200, "text/html; charset=utf-8", BAD)})
    assert main([s.base + "/"]) == 1
    assert s.requests[0][3] == USER_AGENT == "schema-lint/1.0 (+https://github.com/dreadmoreeee/schema-lint)"
    assert f"## {s.base}/" in capsys.readouterr().out


def test_http_error_exits_2(site, capsys):
    s = site({})
    assert main([s.base + "/nope"]) == 2
    assert "HTTP 404" in capsys.readouterr().err


def test_crawl_same_origin_robots_cdn_cgi_and_delay(site, capsys):
    other = site({"/": (200, "text/html", GOOD)})
    page = '<a href="/a">a</a><a href="/private/x">p</a><a href="/cdn-cgi/l/email-protection">e</a>' \
           f'<a href="{other.base}/">elsewhere</a><a href="/logo.png">img</a><a href="/a#frag">again</a>'
    s = site({
        "/robots.txt": (200, "text/plain", "User-agent: *\nAllow: /\nDisallow: /private/\n"),
        "/": (200, "text/html", GOOD.replace("hello", page)),
        "/a": (200, "text/html", BAD.replace("hello", '<a href="/">home</a><a href="/b">b</a>')),
        "/b": (200, "text/html", "<p>no data</p>"),
    })
    start = time.monotonic()
    assert main([s.base + "/", "--crawl", "--format", "json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert s.paths() == ["/robots.txt", "/", "/a", "/b"]
    assert other.requests == []
    urls = [p["url"][len(s.base):] for p in data["pages"]]
    assert urls == ["/", "/a", "/private/x", "/b"]
    assert data["pages"][2]["findings"][0]["code"] == "robots-disallowed"
    times = [t for t, *_ in s.requests]
    assert all(b - a >= 0.95 for a, b in zip(times, times[1:]))
    assert time.monotonic() - start >= 2.9


def test_crawl_respects_max_pages(site, capsys):
    s = site({"/robots.txt": (404, "text/plain", ""),
              "/": (200, "text/html", '<a href="/1">1</a><a href="/2">2</a>'),
              "/1": (200, "text/html", "x"), "/2": (200, "text/html", "y")})
    assert main([s.base + "/", "--crawl", "--max-pages", "2", "--format", "json"]) == 0
    assert s.paths() == ["/robots.txt", "/", "/1"]


def test_python_dash_m_entry_point(tmp_path):
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    r = subprocess.run([sys.executable, "-m", "schema_lint", "--version"], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.startswith("schema-lint 1.")
