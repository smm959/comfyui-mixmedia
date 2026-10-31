# ComfyUI MixMedia на Windows

Приложения в виде готового `.exe` здесь нет: venv с torch и сам Python собираются только на Windows,
а эта сборка сделана на macOS. Вместо этого — установщик-скрипт, который делает всё на твоей машине.

## Установка

1. Нужен **Python 3.11+** (python.org, с галочкой «Add python.exe to PATH») и **git**.
2. Правый клик по `install.ps1` → **Выполнить с помощью PowerShell**.
   Если Windows ругается на политику запуска:
   ```powershell
   powershell -ExecutionPolicy Bypass -File install.ps1
   ```
3. Дождаться: скрипт клонирует ComfyUI, создаст venv, поставит torch и зависимости, скопирует ноды и
   воркфлоу, положит ключ (если передать `-Key`) и сделает ярлык на рабочем столе.

Полезные параметры:

```powershell
.\install.ps1 -Key 02abc...                 # сразу записать ключ MixMedia в %USERPROFILE%\.mixmedia_key
.\install.ps1 -ComfyUI "D:\ComfyUI"         # использовать уже установленный ComfyUI
.\install.ps1 -Cpu                          # torch без CUDA (если нет видеокарты NVIDIA)
```

## Запуск

Ярлык **ComfyUI MixMedia** на рабочем столе → поднимает сервер и открывает UI в отдельном окне
(Chrome в режиме `--app`, без вкладок и адресной строки).

* окно закрыл — сервер остался, повторный запуск мгновенный;
* остановить: диспетчер задач → `python.exe`, либо `taskkill /IM python.exe /F`;
* лог: `%LOCALAPPDATA%\ComfyUI Mix Media\server.log`;
* ключ: `%USERPROFILE%\.mixmedia_key`.

## Что делать, если не завелось

Этот установщик не проверялся на живой Windows. Если что-то падает — пришли текст ошибки из консоли,
поправлю. Самые частые места:

| Симптом | Причина |
|---|---|
| `Не найден Python 3.11+` | python.org без «Add python.exe to PATH» |
| `Нет git` | не установлен Git for Windows |
| долго ставится torch | это норма, ~2.5 ГБ с сайта pytorch |
| UI открылся в браузере, а не в окне | нет Chrome в стандартном пути |
