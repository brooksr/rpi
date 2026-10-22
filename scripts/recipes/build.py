#!/usr/bin/env python3
"""Build a native HA recipe dashboard from the copied family recipe book."""
import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
# source.txt and the doc link are personal; they come from the gitignored copy
# and .env (exported by config.sh).
SOURCE_URL = os.environ.get('RECIPES_DOC_URL', '')
TITLE = os.environ.get('RECIPE_BOOK_TITLE', 'Family Recipe Book')
lines = (HERE / 'source.txt').read_text().splitlines()
titles = [m[1] for line in lines if (m := re.fullmatch(r'(.+?)\s{2,}(\d+)', line))]
# This final recipe is in the document but not its table of contents.
titles.append('Walnut Pepper Biscotti')
positions = [lines.index(title) for title in titles]
assert positions == sorted(positions), 'Recipe headings must follow document order'
recipes = []
for index, (title, start) in enumerate(zip(titles, positions)):
    end = positions[index + 1] if index + 1 < len(positions) else len(lines)
    body = '\n'.join(line.strip() for line in lines[start + 1:end] if line.strip() != '________________').strip()
    assert body, f'Empty recipe: {title}'
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
    recipes.append({'title': title, 'path': slug, 'body': body})
assert len({r['path'] for r in recipes}) == len(recipes)
photos = json.loads((HERE / 'images.json').read_text())

def split_recipe(recipe):
    """Keep every source line, including grouped ingredients and family notes."""
    body = recipe['body']
    if recipe['path'] == 'walnut-pepper-biscotti':
        ingredients, instructions = body.split('Sift first four ingredients', 1)
        return '\n'.join('* ' + line for line in ingredients.strip().splitlines()), 'Sift first four ingredients' + instructions
    source_lines = body.splitlines()
    ingredients, instructions = [], []
    for index, line in enumerate(source_lines):
        if not line:
            ingredients.append('')
            instructions.append('')
        elif line.startswith('* '):
            ingredients.append(line)
        elif re.match(r'^\d+\.', line):
            instructions.append(line)
        elif re.match(r'^\d+\s+(servings|pieces)$', line, re.I):
            ingredients.append(line)
        else:
            following = next((s for s in source_lines[index + 1:] if s), '')
            if following.startswith('* '):
                ingredients.extend(['', '### ' + line, ''])
                if line in ('Filling', 'Dough'):
                    instructions.extend(['', '### ' + line, ''])
            elif line in ('Slow cooker version', 'Stove top version'):
                instructions.extend(['', '### ' + line, ''])
            else:
                instructions.append(line)
    clean = lambda rows: re.sub(r'\n{3,}', '\n\n', '\n'.join(rows)).strip()
    assert clean(ingredients) and clean(instructions), recipe['title']
    return clean(ingredients), clean(instructions)

source = f'the [original Google Doc]({SOURCE_URL})' if SOURCE_URL else 'the original Google Doc'
intro = f'# {TITLE}\n\n{len(recipes)} family recipes · copied October 12, 2026\n\nChoose a recipe below. Ingredients, directions, and family notes are copied from {source}.'
full_width = {'columns': 'full', 'rows': 'auto'}
# Native sections keep equal phone gutters; the theme's masonry view reserves
# an extra right-hand strip that leaves the recipe list visibly off center.
views = [{'title': 'Recipes', 'path': 'index', 'icon': 'mdi:book-open-page-variant',
          'type': 'sections', 'max_columns': 3, 'sections': [
              {'type': 'grid', 'column_span': 3, 'cards': [
                  {'type': 'markdown', 'content': intro, 'grid_options': full_width}]}]}]
for label, group in [('A–C', [r for r in recipes if r['title'][0].upper() <= 'C']), ('D–L', [r for r in recipes if 'D' <= r['title'][0].upper() <= 'L']), ('M–Z', [r for r in recipes if r['title'][0].upper() >= 'M'])]:
    links = '\n\n'.join(f"- [{r['title']}](/family-recipes/{r['path']})" for r in sorted(group, key=lambda r: r['title'].casefold()))
    views[0]['sections'].append({'type': 'grid', 'cards': [
        {'type': 'markdown', 'title': label, 'content': links, 'grid_options': full_width}]})
for recipe in recipes:
    ingredients, instructions = split_recipe(recipe)
    photo = photos[recipe['path']]
    assert (HERE / 'images' / (recipe['path'] + '.jpg')).is_file(), recipe['path']
    credit = f"Example photo · [{photo['credit']}]({photo['source_url']})"
    if photo['license_url']:
        credit += f" · [{photo['license']}]({photo['license_url']})"
    full_width = {'columns': 'full', 'rows': 'auto'}
    views.append({
        'title': recipe['title'], 'path': recipe['path'], 'subview': True,
        'back_path': '/family-recipes/index', 'type': 'sections', 'max_columns': 2,
        'sections': [
            {'type': 'grid', 'cards': [
                {'type': 'markdown', 'title': 'Ingredients', 'content': ingredients, 'grid_options': full_width},
                {'type': 'picture', 'image': '/local/recipes/' + recipe['path'] + '.jpg', 'alt_text': 'Representative example of ' + recipe['title'], 'tap_action': {'action': 'none'}, 'grid_options': full_width},
                {'type': 'markdown', 'content': credit, 'grid_options': full_width},
            ]},
            {'type': 'grid', 'cards': [
                {'type': 'markdown', 'title': 'Instructions', 'content': instructions, 'grid_options': full_width},
            ]},
        ],
    })
# JSON is valid YAML, and preserves source punctuation and quantities exactly.
(HERE / 'dashboard.yaml').write_text(json.dumps({'title': 'Recipes', 'views': views}, ensure_ascii=False, indent=2) + '\n')
# The Overview's recipe card picks from this index (titles, paths, photo credits).
index = [{'title': r['title'], 'path': r['path'], 'credit': photos[r['path']]['credit']} for r in sorted(recipes, key=lambda r: r['title'].casefold())]
(HERE / 'recipes.json').write_text(json.dumps(index, ensure_ascii=False, indent=1) + '\n')
print(f'Built {len(recipes)} recipes, {len(views)} views')
