# easyNAMD

GUI для подготовки молекулярно-динамических систем в VMD с последующим моделированием в NAMD.

> Early development. Do not use for commercial purposes without the author's permission.

## Что умеет (сейчас)

Пошаговая сборка системы через вкладки:

1. **Build PSF** — сборка PSF/PDB из локального `.pdb` файла через `psfgen`
2. **Solvate** — гидратация в TIP3P водный бокс с заданным отступом
3. **Ionize** — нейтрализация системы, опционально с заданной концентрацией соли (NaCl)

Генерирует Tcl-скрипт и запускает VMD headlessly. Лог VMD отображается в реальном времени.

## Зависимости

- [VMD](https://www.ks.uiuc.edu/Research/vmd/) (настраивается при первом запуске)
- Python 3.12+
- [uv](https://github.com/astral-sh/uv)

## Запуск

```bash
uv run python main.py
```

При первом запуске приложение попробует найти VMD автоматически. Путь можно изменить во вкладке **Settings**.

## Силовые поля

Файлы топологий и параметров CHARMM36 лежат в:

```
topologies/          # .rtf, .str — белок, вода, липиды, нуклеиновые кислоты
└── ligands/         # топологии лигандов

parameters/          # .prm, .str
└── ligands/         # параметры лигандов
```

Лигандные файлы (из CGenFF или аналогов) подгружаются через кнопку **Add** на вкладке Build PSF.

## Структура проекта

```
main.py
gui/
  app.py             # главное окно, вкладки Build / Settings
  build_panel.py     # пошаговые вкладки сборки системы
core/
  tcl_writer.py      # генерация Tcl-скриптов (psfgen, solvate, autoionize)
  vmd_runner.py      # запуск VMD через subprocess
topologies/
parameters/
```
