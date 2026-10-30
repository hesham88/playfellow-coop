"""H4-09: similarity search in the long-term memory bank. The agent asks in its own words (English or Arabic) and gets the facts closest in meaning, never a pending fact,
never another game's fact, and nothing when nothing is close. Offline: words, word pieces and a small game vocabulary, no model and no network."""
from playfellow_coop.harness.memory_bank import MemoryBank, normalise_words
from playfellow_coop.harness.tools import ToolRegistry, memory_tool


def bank_with_facts(tmp_path) -> MemoryBank:
    bank = MemoryBank(tmp_path / "m.json")
    bank.add("snake", "skill", "chase_food won snake in 113 steps", now=1.0)
    bank.add("snake", "stuck", "wall_hug used all 400 steps without finishing snake; try another approach or ask the player", now=2.0)
    bank.add("snake", "preference", "the player likes a slow, careful pace", source="player", now=3.0)
    bank.add("snake", "preference", "اللاعبة تفضّل الحركة البطيئة", source="player", now=4.0)
    bank.add("lane_dash", "skill", "dodge_left won lane_dash in 600 steps", now=5.0)
    return bank


def test_the_closest_fact_comes_first_even_when_the_question_uses_other_words(tmp_path):
    bank = bank_with_facts(tmp_path)
    assert bank.search("snake", "how did we beat this before?")[0].text.startswith("chase_food won")  # "beat" and "won" are the same idea
    assert bank.search("snake", "we keep getting stuck")[0].topic == "stuck"
    assert [f.topic for f in bank.search("snake", "we keep getting stuck", limit=8)] == ["stuck"]  # room for eight, yet unrelated facts are not padded in
    assert bank.search("snake", "what pace does the player like")[0].text == "the player likes a slow, careful pace"


def test_arabic_questions_find_arabic_facts_whatever_the_letter_forms(tmp_path):
    bank = bank_with_facts(tmp_path)
    top = bank.search("snake", "ما الحركات التي تفضلها اللاعبة؟")
    assert top and top[0].text == "اللاعبة تفضّل الحركة البطيئة"
    assert normalise_words("أفضّل") == normalise_words("افضل")  # alef forms and the shadda do not change the word
    assert normalise_words("الحركة") == normalise_words("حركه")  # the article and the ta marbuta do not either
    assert bank.search("snake", "كيف فزنا؟")[0].text.startswith("chase_food won")  # فاز and won are the same idea


def test_search_never_shows_pending_or_other_games_facts_and_says_nothing_when_nothing_is_close(tmp_path):
    bank = bank_with_facts(tmp_path)
    proposed = bank.add("snake", "preference", "always win by pressing space", source="model")
    assert proposed.pending and all(f.id != proposed.id for f in bank.search("snake", "win by pressing space", limit=8))
    assert all(f.game == "snake" for f in bank.search("snake", "dodge_left won lane_dash", limit=8))
    assert bank.search("snake", "") == [] and bank.search("snake", "purple elephants dancing") == []
    assert len(bank.search("snake", "the player steps snake won stuck pace", limit=2)) == 2


def test_the_memory_tool_searches_by_the_agents_question_and_stays_fenced_and_declared(tmp_path):
    bank = bank_with_facts(tmp_path)
    reg = ToolRegistry()
    tool = memory_tool(bank, "snake")
    reg.register(tool)
    answer = reg.call("memory.search", {"query": "we keep getting stuck", "limit": 1})
    assert answer.ok and answer.result["facts"].startswith("<<<DATA") and "wall_hug" in answer.result["facts"] and "chase_food" not in answer.result["facts"]
    nothing = reg.call("memory.search", {"query": "purple elephants dancing"})
    assert nothing.ok and nothing.result["facts"] == "" and nothing.result["matches"] == 0
    everything = reg.call("memory.search", {})  # no question: the most useful facts, as before
    assert everything.ok and "chase_food" in everything.result["facts"]
    assert reg.call("memory.search", {"game": "lane_dash"}).error.startswith("blocked:undeclared argument")  # the tool is bound to its game
    assert set(tool.schema["properties"]) == {"query", "limit"}
