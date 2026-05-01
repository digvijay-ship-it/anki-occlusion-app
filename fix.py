import sys

def fix_file(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()

    # Add import if not present at top
    if 'import ui.home_screen' not in content.splitlines()[0:20]:
        content = content.replace('import random, json, os, threading, math', 
                                  'import random, json, os, threading, math\nimport ui.home_screen')

    content = content.replace('"Orbitron"', 'ui.home_screen.NARUTO_FONT_FAMILY')
    content = content.replace("'Orbitron'", 'ui.home_screen.NARUTO_FONT_FAMILY')
    content = content.replace('"Share Tech Mono"', 'ui.home_screen.NARUTO_FONT_FAMILY')
    content = content.replace("'Share Tech Mono'", 'ui.home_screen.NARUTO_FONT_FAMILY')

    # Remove the misaligned import I injected earlier
    content = content.replace('import ui.home_screen\n        hero.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY,28,QFont.Black))', 
                              '        hero.setFont(QFont(ui.home_screen.NARUTO_FONT_FAMILY,28,QFont.Black))')

    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)

fix_file('ui/math_trainer.py')
print('Fixed math_trainer.py')
