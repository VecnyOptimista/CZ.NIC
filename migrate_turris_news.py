#!/usr/bin/env python3
import os
import json
import pytz
import re

import django
django.setup()

from aldryn_newsblog.cms_appconfig import NewsBlogConfig
from aldryn_newsblog.models import Article
from aldryn_people.models import Person
from cms.models import Placeholder
from datetime import datetime, timedelta
from django.contrib.auth import get_user_model
from django.core.files import File as DjangoFile
from django.utils.translation import activate
from filer.models.foldermodels import Folder
from filer.settings import FILER_IMAGE_MODEL
from filer.utils.loader import load_model


def migrate_text(text, user, WORKING_DIR):
    images_count = 0

    if '<embed' in text:
        pattern = re.compile(r'(<embed alt="([\W\w\s_][^"]+)" embedtype="image" format="(fullwidth|left|right)" id="(\d+)"/>)')
        result = pattern.findall(text)

        # Load meta data about images
        image_meta_list = json.load(open(WORKING_DIR + '/data_for_migration/images.news.json', "r"))

        # Image model
        Image = load_model(FILER_IMAGE_MODEL)

        # Images migration
        for match in list(result):
            image_id = int(match[3])  # ID

            meta = next((image for image in image_meta_list if image["pk"] == image_id), False)
            assert meta, "PK {} was not found in the list of meta data".format(image_id)
            file_name = meta['fields']['file'].replace('original_images/', '')
            file_path = WORKING_DIR + '/data_for_migration/original_images/' + file_name

            # Create folder if does not exist
            Folder.objects.get_or_create(
                name = "News images",
                owner=user,
            )
            created_folder = Folder.objects.get(name="News images")

            # Create image if does not exist
            if not Image.objects.filter(name=meta['fields']['title'], folder=created_folder).exists():
                # Load image
                file_obj = DjangoFile(open(file_path, 'rb'), name=file_name)

                created_image = Image.objects.create(
                    owner=user,
                    folder=created_folder,
                    name=meta['fields']['title'],
                    original_filename=file_name,
                    file=file_obj,
                    is_public=True
                )
                images_count += 1

                created_image.save()
            else:
                created_image = Image.objects.get(name=meta['fields']['title'], folder=created_folder)

            new_image = '<a href="{src}" target="_blank"><img alt="{alt}" title="{title}" class="{cls}" src="{src}" id="{id}"/></a>'.format(
                alt=match[1], title=meta['fields']['title'], cls='', src=created_image.url, id=created_image.id)

            text = text.replace(match[0], new_image)
    assert '<embed' not in text, "There is still embed tag in the text. \n\n {}".format(text)

    text = text.replace('<p><br/></p>', '')
    text = text.replace('<br/>', '')
    text = text.replace('<p class=""></p>', '')
    text = text.replace('<p></p>', '')

    return text, images_count

def main():
    User = get_user_model()
    TZ_PRAGUE = pytz.timezone('Europe/Prague')

    ARTICLES_LIMIT = 666
    WORKING_DIR = os.path.dirname(os.path.abspath(__file__))
    print('Path, where data files are: ', WORKING_DIR)

    missing_cs_content_counter = 0
    missing_en_content_counter = 0
    number_of_cs_articles_created = 0
    number_of_en_articles_created = 0
    number_of_images_created = 0

    DATA = json.load(open(WORKING_DIR + '/data_for_migration/old_news.json', "r"))

    # Defining
    user = User.objects.get(username='admin')
    another_app_config = NewsBlogConfig.objects.get(pk=1)  # Use current settings

    # Create articles
    for counter, article in enumerate(DATA):
        assert not article['expire_at'] and not article['expired'], "Article {} is expired!".format(counter)

        if not article['text_cs'] and not article['perex_cs']:
            missing_cs_content_counter += 1
            continue
        if not article['text_en'] and not article['perex_en']:
            missing_en_content_counter += 1

        exists = Article.objects.filter(translations__title=article['title_cs']).exists()

        if not exists:  # Prevents creating duplicates
            cs_text, images_count = migrate_text(article['text_cs'] if article['text_cs'] else article['perex_cs'], user, WORKING_DIR)
            number_of_images_created += images_count
            cs = {
                "title": article['title_cs'],
                "slug": article['slug_cs'],
                "lead_in": cs_text,
            }

            en_text, images_count = migrate_text(article['text_en'] if article['text_en'] else article['perex_en'], user, WORKING_DIR)
            number_of_images_created += images_count
            en = {
                "title": article['title'],
                "slug": article['slug'],
                "lead_in": en_text,
            }

            converted_date = datetime.strptime(article['date'], '%Y-%m-%d')
            publishing_date = TZ_PRAGUE.localize(converted_date + timedelta(hours=6))

            # Creating articles
            obj_article = Article(
                is_published=True,
                publishing_date=publishing_date,
                app_config=another_app_config,
                owner=user,
            )
            obj_article.save_base()
            obj_article.create_translation(language_code='cs', **cs)
            number_of_cs_articles_created += 1
            if article['text_en'] or article['perex_en']:
                obj_article.create_translation(language_code='en', **en)
                number_of_en_articles_created += 1

        if counter >= ARTICLES_LIMIT-1:
            break

    print('Number of created CS articles: ' + str(number_of_cs_articles_created))
    print('Number of created EN articles: ' + str(number_of_en_articles_created))
    print('Number of created images: ' + str(number_of_images_created))

    print('Number of missing CS contents: ' + str(missing_cs_content_counter))
    print('Number of missing EN contents: ' + str(missing_en_content_counter))

if __name__ == '__main__':
    main()
