# MCPDrift Manual

## Запуск на реальных LLM

Сейчас в репозитории поддержан реальный запуск через Anthropic API.
Фактически это означает:

- модель вызывается реально через Claude;
- инструменты остаются mock/simulated;
- полноценный defense sweep пока все еще завязан на `MockAgentHarness`.

OpenAI упомянут в документации как опциональный провайдер, но в текущем коде реальный harness реализован только для Anthropic.

## Что нужно заранее

- Python 3.11+
- Anthropic API key
- локально установленные зависимости проекта

## Установка

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .[dev]
```

## Настройка API key

В проекте есть зависимость `python-dotenv`, но `.env` автоматически не загружается.
Поэтому ключ нужно явно выставить в текущую PowerShell-сессию:

```powershell
$env:ANTHROPIC_API_KEY="sk-ant-..."
```

Проверить можно так:

```powershell
python -c "import os; print(bool(os.environ.get('ANTHROPIC_API_KEY')))"
```

## Claude Pro, Copilot Pro+ и Anthropic API

Это три разные вещи.

- `Claude Pro` дает доступ к Claude через веб-интерфейс claude.ai, но не дает API key для Python-кода.
- `GitHub Copilot Pro+` дает доступ к моделям внутри GitHub Copilot, но не подставляется напрямую в текущий `AgentHarness`.
- `Anthropic API` дает API key, который нужен текущей реализации для автоматического запуска сценариев.

Для этого репозитория важно именно последнее: текущий реальный запуск завязан на `ANTHROPIC_API_KEY`.

Что это значит practically:

- через `Claude Pro` можно общаться с моделью вручную, но не запускать этот benchmark как есть;
- через `GitHub Copilot Pro+` можно пользоваться Copilot в редакторе, но нельзя просто подменить им `ANTHROPIC_API_KEY`;
- для автоматического batch-run из Python нужен именно Anthropic API или отдельная новая интеграция под другой провайдер.

Теоретически проект можно расширить под другой backend, например GitHub Models, но такой harness в текущем коде еще не реализован.

## Полу-ручный режим без API

Если у вас есть `Claude Pro` или `GitHub Copilot Pro+`, но нет API key, можно использовать полу-ручный режим.

Идея простая:

1. MCPDrift собирает prompt для очередного хода.
2. Вы вставляете этот prompt в Claude Pro или Copilot Chat.
3. В идеале модель отвечает JSON-объектом с `response_text` и `tool_calls`.
4. Вы вставляете этот JSON обратно в терминал.
5. MCPDrift сам исполняет mock tools локально, накапливает history и сохраняет `SessionTrace`.

### Команда запуска

```powershell
python -m mcpdrift.harness.manual_runner --scenario mcpdrift/attacks/multiturn/mt_delayed_ssh.json --model-label claude-pro-manual
```

Для GitHub Copilot Chat можно просто поменять label:

```powershell
python -m mcpdrift.harness.manual_runner --scenario mcpdrift/attacks/multiturn/mt_delayed_ssh.json --model-label copilot-pro-plus-manual
```

### Как пользоваться

После запуска runner выведет prompt для текущего turn. Его нужно целиком вставить в Claude Pro или Copilot Chat.

Лучший вариант: попросить модель вернуть только JSON следующего вида:

```json
{
    "response_text": "assistant response text",
    "tool_calls": [
        {
            "tool_name": "file_read",
            "parameters": {
                "path": "/data/project/readme.md"
            }
        }
    ]
}
```

Если модель отказывается и пишет обычный текст вроде "это prompt injection атака, я отказываюсь", это тоже допустимо. Теперь manual runner умеет принять такой plain-text ответ как валидный benchmark outcome: он сохранит этот текст в `response_text`, а `tool_calls` выставит в пустой список.

То есть ваш пример с отказом Claude не нужно выбрасывать. Его можно просто целиком вставить обратно в терминал и завершить строкой `END`.

Затем этот JSON нужно вставить обратно в терминал и завершить ввод строкой:

```text
END
```

После этого MCPDrift:

- выполнит указанные tool calls через mock implementations;
- подставит tool results в history;
- сформирует prompt для следующего turn;
- в конце сохранит trace в `results/traces`;
- сразу выведет `Judge verdicts` по каждому ходу, включая `refused`, `ignored`, `partial`, `success`.

### Ограничения полу-ручного режима

- Это медленнее, чем API-run, потому что каждый turn требует copy/paste.
- Модель может иногда не соблюдать JSON-only формат; в этом случае runner попросит вставить ответ еще раз.
- Plain-text refusal тоже допустим, в том числе на русском языке.
- Воспроизводимость ниже, чем при `temperature=0` через API.
- Defense benchmark в этом режиме автоматически не прогоняется.

## Запуск одного сценария на Claude

Этот вариант полезен для быстрой проверки конкретной атаки.

```powershell
@'
from mcpdrift.harness.agent_harness import AgentHarness
from mcpdrift.harness.scenario_runner import ScenarioRunner

harness = AgentHarness(
    model="claude-sonnet-4-6",
    temperature=0.0,
)

runner = ScenarioRunner(
    harness=harness,
    output_dir="results/traces",
)

trace = runner.run_scenario("mcpdrift/attacks/multiturn/mt_delayed_ssh.json")
print(trace.model_dump_json(indent=2))
'@ | python
```

Результат:

- trace печатается в stdout;
- JSON trace автоматически сохраняется в `results/traces`.

## Запуск всех сценариев с подсчетом метрик

Этот вариант прогоняет все JSON-сценарии из `mcpdrift/attacks/`, затем считает judge verdicts, turn scores и aggregate metrics.

```powershell
@'
import json
from pathlib import Path

from mcpdrift.harness.agent_harness import AgentHarness
from mcpdrift.harness.scenario_runner import ScenarioRunner
from mcpdrift.evaluation.judge import TurnJudge
from mcpdrift.evaluation.turn_scorer import TurnScorer
from mcpdrift.evaluation.metrics import compute_all_metrics

harness = AgentHarness(
    model="claude-sonnet-4-6",
    temperature=0.0,
)

runner = ScenarioRunner(
    harness=harness,
    output_dir="results/traces",
)

scenario_root = Path("mcpdrift/attacks")
recovery_dir = scenario_root / "recovery"
scenario_paths = [
    path
    for path in sorted(scenario_root.rglob("*.json"))
    if path.name != "schema.json" and recovery_dir not in path.parents
]
scored_sessions = []
session_classes = {}

for path in scenario_paths:
    scenario = json.loads(path.read_text(encoding="utf-8"))
    trace = runner.run_scenario(str(path))

    judge = TurnJudge(
        poisoned_tool_name=scenario["poisoned_tool"]["name"],
        attacker_goal=scenario["attacker_goal"],
        user_goal=scenario["user_goal"],
    )
    verdicts = judge.judge_session(trace.turns)

    scored = TurnScorer(
        poisoned_tool_name=scenario["poisoned_tool"]["name"]
    ).score_session(trace, verdicts)

    scored_sessions.append(scored)
    session_classes[scenario["scenario_id"]] = scenario["attack_class"]

metrics = compute_all_metrics(
    scored_sessions,
    session_classes=session_classes,
)

print(metrics.model_dump_json(indent=2))
'@ | python
```

## Что именно происходит при таком запуске

1. `AgentHarness` делает реальный вызов в Anthropic Messages API.
2. `ScenarioRunner` загружает JSON-сценарий и собирает tool descriptions.
3. `MultiTurnEngine` прокидывает в каждый следующий ход всю накопленную историю.
4. Tool calls исполняются локально через mock implementations, чтобы trace содержал конкретные tool results.
5. `TurnJudge`, `TurnScorer` и `compute_all_metrics()` считают итоговые оценки.

## Ограничения текущей реализации

- Реальный запуск сейчас поддержан только для Anthropic.
- `.env` не подхватывается автоматически.
- Полный defense benchmark в `mcpdrift/defenses/benchmark_runner.py` пока использует `MockAgentHarness`, а не реальный `AgentHarness`.
- Реального MCP client/server round-trip пока нет: инструменты исполняются локально через mock tool implementations.

## Рекомендуемый минимальный порядок запуска

1. Сначала прогнать один multi-turn сценарий, например `mt_delayed_ssh.json`.
2. Проверить, что trace появился в `results/traces`.
3. После этого прогнать весь набор сценариев.
4. Отдельно сравнить output metrics с данными из `docs/Report.md`.

## Если нужен следующий шаг

Следующим логичным улучшением будет добавить CLI entrypoint и поддержку real-LLM запуска для defense benchmark, чтобы не пользоваться heredoc-скриптами в PowerShell.
