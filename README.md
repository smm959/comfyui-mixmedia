# ComfyUI + MixMedia: фотостудия на нодах

Кастомные ноды ComfyUI для [MixMedia API](https://mixmedia.tech) (`nano-banana-pro`, `nano-banana-2`,
`gpt-image-2.5`, `seedream`, `flux`) и готовый воркфлоу фотосессии:

**лист персонажа → кадр (одежда, локация, головной убор, поза) → докрутка камеры.**

Промпт не пишется одной простынёй: он собирается из того, что ты накрутил ручками — каждый блок
виден в логе и в `output/_prompts/<дата>.txt`, ничего не зашито в код.

<p align="center"><img src="assets/icon.png" width="140" alt="ComfyUI MixMedia"></p>

> English version: [README.en.md](README.en.md)

Полная инструкция (установка, этапы, кнопка СТАРТ, цены, разбор ошибок, восстановление оплаченных
задач, сборка приложения) — **[README-ru.md](README-ru.md)**.

## Ноды

| Нода | Что делает |
|---|---|
| **MixMedia Character** | 2–6 фото лица → лист персонажа 2×2 (фронт, три четверти, профиль, рост) одной картинкой |
| **MixMedia Shot** | один кадр: персонаж + одежда + локация + убор + поза текстом. Своего промпта не имеет |
| **MixMedia Studio** | камера, свет, объектив, фон, объекты → текстовый бриф для Shot |
| **MixMedia Retake** | докрутить камеру готового кадра: поворот, зум, высота, объектив |
| **MixMedia Ref** | референс из `input` или `(нет)` — пустой вход не ломает запуск |
| **MixMedia Direction** | бриф текстом + две ручки: сила контекста и сила деталей |
| **MixMedia Image** | обычная генерация/редактирование: промпт + любые референсы |
| **MixMedia Balance** | показывает баланс аккаунта |

## Как собирается промпт

`MixMedia Shot` описывает только роли картинок, дальше — блоки от нод:

```
Compose one new photo from these references:
image 1: the person — exact face, hair, body proportions
image 2: the clothes — dress the person in exactly these pieces, including the headwear if the photos show one
image 3: the place — put the person inside this exact space and light

POSE — сидит на подоконнике, колени к груди

CAMERA — full-body framing, head to toe, camera three-quarter left of the model, lens at eye level, 85mm lens.
LIGHT — softbox at 45 degrees from camera left, neutral 5600K, soft.
SET — backdrop: grey cyclorama; add to the frame: a wooden stool; never show: text, logos.
BRIEF — calm expression, sharp eyes
```

* референсы нумеруются автоматически, роли подставляются с реальными номерами;
* `MixMedia Studio` добавляет только то, что не `auto` — остальное не попадает в промпт;
* `pose` — свободный текст: пусто → блок `POSE` не появляется;
* `MixMedia Ref` с `(нет)` просто не отправляет картинку (обычный `LoadImage` пустым оставить нельзя — он падает);
* готовый промпт выходит из ноды третьим выходом `prompt`, пишется в лог и в `output/_prompts/<дата>.txt`.

## Установка

1. Скопируй `custom_nodes/comfyui-mixmedia` в `<ComfyUI>/custom_nodes/`.
2. Положи ключ MixMedia в `~/.mixmedia_key` (одна строка, права `600`). Поле `api_key` в нодах
   оставляй пустым: иначе ключ попадёт в JSON воркфлоу.
3. Перезапусти ComfyUI: ноды появятся в категории `api/mixmedia`.
4. Скопируй `workflows/photostudio_mixmedia.json` в `<ComfyUI>/user/default/workflows/`.

## Воркфлоу фотостудии

Один JSON, три независимых этапа на одном холсте, между собой не связаны:

| Этап | Что делает | Выход |
|---|---|---|
| 1. Персонаж | 6 фото лица → лист 2×2 | `character_ref` |
| 2. Кадр | персонаж + одежда + локация + убор + поза + Studio | `shot` |
| 3. Докрутка | кадр + turn/zoom/высота/объектив | `retake` |

У каждого этапа внизу ноды есть кнопка **«▶ СТАРТ»**: включает свой этап, выключает остальные и сразу
ставит очередь — считается ровно один этап. Ручной способ — галочка **`run`** на ноде
(`Mixmedia Character` / `Mixmedia Shot` / `Mixmedia Retake`). Выключенный этап не выполняется и не тратит
деньги: `SaveImage` пропускается молча, без красного Error Report (в лог уходит строка «выключен»).
По умолчанию включён этап 1. Выходы не мьюкаются никогда, поэтому ComfyUI не ругается «нет выходных узлов».

## Модели и цены

| Модель | Разрешения | Референсы | 1K | 2K | 4K |
|---|---|---|---|---|---|
| `nano-banana-pro` | 1K, 2K, 4K | 8 | $0.05 | $0.05 | $0.065 |
| `nano-banana-2` | 0.5K, 1K, 2K, 4K | 10 | $0.025 | $0.035 | $0.04 |
| `nano-banana` | 1K, 2K | 10 | $0.03 | $0.03 | — |
| `gpt-image-2.5` | 1K, 2K, 4K | 16 | $0.04 | $0.04 | $0.06 |
| `seedream-pro` / `flash` | 1K, 1.5K, 2K | 10 | $0.05 / $0.025 | $0.095 / $0.025 | — |
| `flux-dev` | — | 0 | $0.033 | — | — |

Неподдерживаемое разрешение или пропорция подставляется ближайшая (например, `9:21` → `9:16`),
в консоль уходит предупреждение — задача не падает.

## Проверки

```bash
.venv/bin/python tools/test_prompts.py                 # промпты и execute() без запросов в API
python3 tools/validate_workflow.py workflows/photostudio_mixmedia.json   # сверка с /object_info
node tools/e2e/check-workflows.js workflows/photostudio_mixmedia.json    # загрузка в реальном фронтенде
node tools/e2e/check-link.js workflows/photostudio_mixmedia.json         # линки и значения виджетов
node tools/e2e/check-run.js workflows/photostudio_mixmedia.json          # какие этапы уйдут в очередь
node tools/e2e/slots.js                                                  # порядок входов и виджетов
```

`validate_workflow.py` и e2e-скрипты ждут запущенный ComfyUI на `http://127.0.0.1:8188`.

## Windows

Готового `.exe` нет: venv с torch собирается только на Windows. Вместо него — установщик-скрипт
[`windows/install.ps1`](windows/install.ps1): клонирует ComfyUI, создаёт venv, ставит torch и зависимости,
копирует ноды и воркфлоу, кладёт ключ и делает ярлык на рабочем столе. Ярлык запускает сервер и открывает
UI отдельным окном (Chrome `--app`), как на macOS.

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

Архив со всем нужным лежит в [релизе](https://github.com/smm959/comfyui-mixmedia/releases/tag/v1.0).

> **Нужна помощь:** установщик ни разу не запускался на живой Windows. Если можешь проверить —
> отпишись в [issue #1](https://github.com/smm959/comfyui-mixmedia/issues/1), это займёт 10 минут
> и очень поможет.

## Приложение для macOS

`tools/make_installer.sh` собирает самодостаточное приложение (ComfyUI + venv + ноды внутри бандла) и
DMG-установщик с окном «перетащи в Applications»:

* окно — своё (`desktop/ComfyUIApp.m`: ObjC + WKWebView, ~80 КБ), не вкладка браузера: без адресной
  строки и меню Chrome, с ⌘R / ⌘± и обычным копипастом; размер и положение запоминаются;
* сервер поднимается через launchd (`local.mixmedia.comfyui`) и живёт после закрытия окна;
* ключ при первом запуске переезжает в `~/.mixmedia_key`, в установщик он не попадает;
* сборка окна: `clang` (нужна принятая лицензия Xcode) — `desktop/ComfyUIApp.m`; запасной вариант —
  `pyobjc-framework-WebKit` из `desktop/requirements.txt`, последний — Chrome `--app`;
* нужен `dmgbuild` (`pip install dmgbuild`).

## Ограничения

* MixMedia не принимает `seed` — виджет `seed` только сбрасывает кэш ComfyUI;
* `Cancel` в UI не отменяет уже созданную и оплаченную задачу;
* результат на стороне MixMedia живёт 24 часа, нода скачивает его сразу;
* сеть нода переживает: загрузка и опрос повторяются (опрос — до конца `timeout_sec`, по умолчанию 900 с);
  если всё-таки упало, оплаченную картинку можно забрать руками: `python tools/fetch_task.py <taskId>`;
* лимит референсов у Pro — 8 на запрос, лишние фото личности отрезаются с предупреждением.

## Лицензия

Код открыт для использования как угодно; ComfyUI и MixMedia API — со своими лицензиями и тарифами.
