"""HR Compass — entry point.

Run: python main.py  (or make run); a single question: python main.py "How many vacation days do I get?"
"""

import sys

from hr_compass.chat import main

if __name__ == "__main__":
    sys.exit(main())
