#!/usr/bin/env python3
"""Download the selected example photos and record source/attribution details."""
import html
import json
import re
import subprocess
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
commons = {
    'eggs-benedict': 'Traditional Eggs Benedict.jpg',
    'pancakes-and-waffles': 'Foodiesfeed.com pouring-honey-on-pancakes-with-walnuts.jpg',
    'pasta-fagioli': 'Pasta e fagioli cannellini.jpg',
    'caesar-salad': 'Caesar salad (2).jpg',
    'clam-chowder': 'Quail 07 bg 041506.jpg',
    'curried-chicken-salad': 'Curried Chicken Salad.jpg',
    'congo-bars': 'Hazelnut blondie.jpg',
    'grandma-pearl-s-mexican-chicken-stew': 'Caldo tlalpeño con arroz rojo y tortillas.jpg',
    'cornbread': 'Skillet cornbread (cropped).jpg',
    'dad-s-ribs': 'Spareribs 20160506 182617113.jpg',
    'chili': 'Bowl of chili.jpg',
    'kraut': 'Belarusian-Russian Sauerkraut-1.jpg',
    'grandma-s-bread': 'Garlicbread.jpg',
    'mashed-potatoes': 'Sous vide mashed potatoes.jpg',
    'chicken-pot-pie': 'ChickenpotpieswholeFeb09.jpg',
    'enchiladas': 'Enchilada Rice Beans.jpg',
    'chef-chu-s-mongolian-beef': 'Mongolian Beef with rice and noodles.jpg',
    'jalapa-burritos': 'Burrito.JPG',
    'summer-berry-cobbler': 'Berry cobbler (19558861105).jpg',
    'chicken-marsala': 'Flickr preppybyday 4843102799--Chicken marsala.jpg',
    'lasagna': 'Lasagne - stonesoup.jpg',
    'chicken-and-dumplings': 'Mmm... chicken dumplings (7867591472).jpg',
    'walnut-pepper-biscotti': 'Cantuccini-Toscani.jpg',
}
external = {
    'sopa-de-huevos': ('https://everydaylatina.com/wp-content/uploads/2018/11/fullsizeoutput_2fd-min-1024x683.jpeg', 'https://everydaylatina.com/fast-and-easy-breakfast-huevos-con-tortillas/', 'Everyday Latina'),
    'apricot-bars': ('https://peterskitchen.org/cdn/shop/files/IMG_1876.jpg?v=1712952641', 'https://peterskitchen.org/products/abuelas-apricot-bars-2-dozen', "Peter’s Kitchen"),
    'garlic-lemon-chicken': ('https://sweetcsdesigns.com/wp-content/uploads/2021/05/garlic-lemon-chicken-breasts-recipe-picture-scaled.jpg', 'https://sweetcsdesigns.com/the-best-easy-baked-garlic-lemon-chicken-breasts-recipe/', 'Sweet C’s Designs'),
    'albondigas': ('https://insanelygoodrecipes.com/wp-content/uploads/2024/07/Albondigas-Soup-Mexican-Meatball-Soup-in-a-Bowl.jpg', 'https://insanelygoodrecipes.com/albondigas-soup/', 'Insanely Good'),
    'carrots-and-turnips': ('https://nestle.jp/home/sites/default/files/recipe/2024-01/3015.jpg', 'https://nestle.jp/home/recipes/03015', 'Nestlé Japan'),
    'beef-stew-in-pumpkin': ('https://img.sndimg.com/food/image/upload/f_auto%2Cc_thumb%2Cq_55%2Cw_744%2Car_5%3A4/v1/img/recipes/32/46/7/picfwIEhG.jpg', 'https://www.food.com/recipe/beef-stew-in-a-pumpkin-32467', 'Food.com'),
    'shredded-chicken': ('https://cdn.bakedbree.com/uploads/2024/03/Boiled-Chicken-Boiled-Chicken_CLOSE-UP-2-683x1024.jpg', 'https://bakedbree.com/boiled-chicken', 'Baked Bree'),
    'spanish-rice': ('https://ww2.kqed.org/app/uploads/sites/24/2016/11/mexican-rice-final-1180x787.jpg', 'https://www.kqed.org/bayareabites/113248/mexican-style-thanksgiving-mexican-style-rice', 'Wendy Goodfriend / KQED'),
    'fire-cider': ('https://www.diasporaco.com/cdn/shop/articles/claus_fire_cider_diaspora.jpg?v=1753093379', 'https://www.diasporaco.com/blogs/recipes/clau-s-community-fire-cider', 'Diaspora Co.'),
}

def curl(url, output=None):
    args = ['curl', '-fsSL', '--retry', '3', '--retry-delay', '10', '--max-time', '60', '-A', 'FamilyRecipeBook/1.0 (personal Home Assistant recipe dashboard)']
    if output:
        args += ['-o', str(output)]
    return subprocess.check_output(args + [url])

def plain(value):
    return html.unescape(re.sub('<[^>]+>', '', value)).strip()

params = dict(action='query', format='json', titles='|'.join('File:' + f for f in commons.values()), prop='imageinfo', iiprop='url|extmetadata', iiurlwidth=800)
data = json.loads(curl('https://commons.wikimedia.org/w/api.php?' + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)))
pages = {p['title'][5:]: p for p in data['query']['pages'].values()}
photos = {}
for slug, filename in commons.items():
    info = pages[filename]['imageinfo'][0]
    meta = info['extmetadata']
    photos[slug] = dict(image_url=info.get('thumburl', info['url']).split('?')[0], source_url=info['descriptionurl'], credit=plain(meta.get('Artist', {}).get('value', 'Wikimedia Commons')), license=meta.get('LicenseShortName', {}).get('value', ''), license_url=meta.get('LicenseUrl', {}).get('value', ''), original_file=filename)
for slug, (url, source, credit) in external.items():
    photos[slug] = dict(image_url=url, source_url=source, credit=credit, license='Copyright retained by source', license_url='')
# Save provenance before downloads so a failed request can be diagnosed.
(HERE / 'images.json').write_text(json.dumps(photos, ensure_ascii=False, indent=2) + '\n')
(HERE / 'images').mkdir(exist_ok=True)
for slug, photo in photos.items():
    destination = HERE / 'images' / (slug + '.jpg')
    if not destination.exists():
        curl(photo['image_url'], destination)
    print(slug, flush=True)
