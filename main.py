"""HR Compass — точка входу.

Запуск: python main.py  (або make run); одне питання: python main.py "Скільки днів відпустки?"
"""

import sys

from hr_compass.chat import main

if __name__ == "__main__":
    sys.exit(main())
