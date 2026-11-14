"""Static UI checks: scripts parse, controls exist, code editor is collapsed."""
import re
import json
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Inspector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.details_depth = 0
        self.editor_in_details = False
        self.default_open_details = False
        self.label_targets = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "details":
            self.details_depth += 1
            self.default_open_details |= "open" in attrs
        if "id" in attrs:
            self.ids.append(attrs["id"])
            if attrs["id"] == "editor":
                self.editor_in_details = self.details_depth > 0
        if tag == "label" and "for" in attrs:
            self.label_targets.append(attrs["for"])

    def handle_endtag(self, tag):
        if tag == "details":
            self.details_depth -= 1


def check(path, client=False):
    html = path.read_text(encoding="utf-8")
    page = Inspector()
    page.feed(html)
    assert len(page.ids) == len(set(page.ids)), f"duplicate IDs in {path}"
    for target in page.label_targets:
        assert target in page.ids, f"missing label target {target}"
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    for target in re.findall(r"\$\('([^']+)'\)", script):
        assert target in page.ids, f"missing JavaScript target {target}"
    subprocess.run(["node", "--check"], input=script, text=True, encoding="utf-8", check=True)
    if client:
        assert "{effectsEnabled:true}" in script, "client animations must start enabled"
        assert page.editor_in_details
        assert 'id="behaviorPanel"' in html and 'id="generatedCode"' in html
        assert all("b-" + action in page.ids for action in ("eat", "reproduce", "attack", "defend", "move"))
        assert "serviceUrl" in page.ids and "previewBtn" in page.ids
    else:
        function = re.search(r"function buildLaunchCommand\(\)\{[^\n]+\}", script)
        assert function
        values = {
            "worldGoRules": {"value": "off"}, "worldSeed": {"value": "12"}, "worldPort": {"value": "8766"},
            "worldHttpPort": {"value": "8082"}, "worldSpeed": {"value": "5000"},
            "worldPreset": {"value": "lush"}, "setupMessage": {}, "launchCommand": {},
            "copyCommand": {}, "launchHelp": {}, "worldRulePath": {"value": ""},
            "worldMoveCost": {"value": "2"}, "worldPushCost": {"value": "0"}, "worldBlockAttackCost": {"value": "3"}, "worldAttackCost": {"value": "3"},
            "worldReproduceCost": {"value": "8"}, "worldReproduceMinEnergy": {"value": "10"},
            "worldChildEnergy": {"value": "5"}, "worldEatGain": {"value": "5"},
            "worldAttackRewardPercent": {"value": "50"}, "worldChangeCost": {"value": "1"},
            "worldArmorDefenseBonus": {"value": "3"}, "worldArmorMoveSurcharge": {"value": "1"},
        }
        js = ("const nodes=" + json.dumps(values) + "; const $=id=>nodes[id]; "
              + function.group(0) + "; buildLaunchCommand(); "
              + "if (!nodes.launchCommand.textContent.includes('cellgame server --world-preset lush --tick-ms 5000 --seed 12 --port 8766 --http-port 8082')) throw Error('bad command');"
              + "if (!nodes.launchCommand.textContent.includes('--move-cost 2') || !nodes.launchCommand.textContent.includes('--eat-gain 5') || !nodes.launchCommand.textContent.includes('--push-cost 0') || !nodes.launchCommand.textContent.includes('--block-attack-cost 3')) throw Error('missing economic options');"
              + "nodes.worldHttpPort.value='8766'; buildLaunchCommand();"
              + "if (!nodes.launchCommand.hidden) throw Error('invalid ports accepted');")
        subprocess.run(["node", "-e", js], text=True, encoding="utf-8", check=True)


def main():
    check(ROOT / "client" / "console.html", True)
    check(ROOT / "server" / "spectator.html")
    subprocess.run(["node", "--check", str(ROOT / "shared" / "world_view.js")], check=True)
    subprocess.run(["node", str(ROOT / "tests" / "world_view_test.js")], check=True)
    print("UI CONTRACT TEST PASSED")


if __name__ == "__main__":
    main()
