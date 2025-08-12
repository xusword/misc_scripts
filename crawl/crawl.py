import argparse
import logging
import time
import urllib.request

from enum import Enum
from html.parser import HTMLParser

def get_attr(attrs, attr_name):
    for (k, v) in attrs:
        if k == attr_name:
            return v
        
def in_attr(attrs, attr_name, segment):
    attr_value = get_attr(attrs, attr_name)
    if attr_value:
        return segment in attr_value
    else:
        return False


class ParseStatus(Enum):
    NOT_STARTED = 0
    TITLE = 1
    CONTENT_DIV = 2
    CONTENT_IMAGE = 3

class LinkTextExtractor(HTMLParser):
    def __init__(self, substrings_to_find: list[str], current_url: str):
        super().__init__()
        self.substrings_to_find = substrings_to_find
        self.current_url = current_url
        self.in_title = False
        self.status = ParseStatus.NOT_STARTED
        self.block_image_element = None
        self.div_level = 0

    def handle_starttag(self, tag, attrs):
        match(self.status):
            case ParseStatus.NOT_STARTED:
                if attrs and in_attr(attrs, "class", "wp-block-post-title"):
                    self.status = ParseStatus.TITLE
            
            case ParseStatus.TITLE:
                if tag == 'div':
                    self.status = ParseStatus.CONTENT_DIV
                    self.div_level += 1

            case ParseStatus.CONTENT_DIV:
                if attrs and in_attr(attrs, "class", "wp-block-image"):
                    self.block_image_element = tag      # block_image_element would be a "figure" that denotes preview image
                    self.status = ParseStatus.CONTENT_IMAGE
                    return
                
                match(tag):
                    case 'a':
                        if self.current_title:
                            link = get_attr(attrs, "href")
                            print(link)

                    case 'div':
                        self.div_level += 1
                
            case ParseStatus.CONTENT_IMAGE:
                if self.block_image_element == tag:
                    raise Exception(f"NESTED BLOCK IMAGE ELEMENT {tag}")


    def handle_endtag(self, tag):
        match(self.status):
            # the whole div is done
            case ParseStatus.CONTENT_DIV:
                if tag == 'div':
                    self.div_level -= 1
                    if self.div_level < 0:
                        logging.error("div level went under 0")
                        self.div_level = 0
                    if self.div_level == 0:
                        self.status = ParseStatus.NOT_STARTED

            # preview image closed
            case ParseStatus.CONTENT_IMAGE:
                if tag == self.block_image_element:
                    self.block_image_element = False
                    self.status = ParseStatus.CONTENT_DIV


    def handle_data(self, data):
        # ignore empty stuff
        if not data.strip():
            return
        
        match(self.status):
            case ParseStatus.TITLE:
                for s in self.substrings_to_find:
                    if s in data:
                        self.current_title = data
                        print(f"{s} found in {self.current_url}: {self.current_title}")
                        return
                # If no title match, reset
                self.current_title = None


def read_keywords_from_file(filepath: str) -> list[str]:
    keywords = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            stripped_line = line.strip()
            if stripped_line:
                keywords.append(stripped_line)
    return keywords

def crawl_site(keywords: list[str], url_prefix: str, start_page: int = 0, end_page: int = 0):
    for i in range(start_page, end_page):
        page_url = f"{url_prefix}/{i}"
        try:
            logging.info(f"opening pageg {page_url}")
            with urllib.request.urlopen(page_url) as response:
                html_content = response.read().decode('utf-8')
            parser = LinkTextExtractor(keywords, page_url)
            parser.feed(html_content)

        except urllib.error.URLError as e:
            print(f"  Error visiting {page_url}: {e.reason}")
        except Exception as e:
            print(f"  An unexpected error occurred for {page_url}: {e}")

        # Wait for 10 seconds before the next request
        if i < end_page - 1:
            logging.debug(f"Waiting for 10 seconds before visiting the next page...")
            time.sleep(10)

    logging.info("Crawling finished.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Crawl web pages to find links containing specific keywords."
    )
    parser.add_argument(
        "--keywords_file",
        type=str,
        default="keywords.txt",
    )
    parser.add_argument(
        "--url_prefix",
        type=str,
        default="https://site.com",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=1,
    )
    parser.add_argument(
        "--end",
        type=int,
        default=50,
    )
    parser.add_argument(
        "--log_level",
        type=str,
        default="debug",
        choices=["debug", "info", "warning", "error", "critical"]
    )

    args = parser.parse_args()
    logging.basicConfig(level=logging._nameToLevel[args.log_level.upper()], format='[%(levelname)s]: %(message)s')
    keywords = read_keywords_from_file(args.keywords_file)
    crawl_site(keywords, args.url_prefix, args.start, args.end)
