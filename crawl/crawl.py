import argparse
import logging
import os
import shutil
import time
import urllib.request

from abc import abstractmethod
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

newline = "\n"

class SiteCrawler(HTMLParser):
    def __init__(self, current_url: str):
        super().__init__()
        self.current_url = current_url
        self.in_title = False
        self.status = ParseStatus.NOT_STARTED
        self.block_image_element = None
        self.div_level = 0
        self.post_link = None
        self.current_title = None
        self.title_position = 0
        self.content_links = []
        self.is_done = False

    @abstractmethod
    def handle_post_end(self):
        raise NotImplementedError()

    @abstractmethod
    def handle_post_title(self):
        raise NotImplementedError()

    def handle_starttag(self, tag, attrs):
        match(self.status):
            case ParseStatus.NOT_STARTED:
                if attrs and in_attr(attrs, "class", "wp-block-post-title"):
                    self.status = ParseStatus.TITLE
                    self.title_position += 1
            
            case ParseStatus.TITLE:
                match(tag):
                    case 'div':
                        self.status = ParseStatus.CONTENT_DIV
                        self.div_level += 1
                    case 'a':
                        self.post_link = get_attr(attrs, "href")

            case ParseStatus.CONTENT_DIV:
                if attrs and in_attr(attrs, "class", "wp-block-image"):
                    self.block_image_element = tag      # block_image_element would be a "figure" that denotes preview image
                    self.status = ParseStatus.CONTENT_IMAGE
                    return
                
                match(tag):
                    case 'a':
                        link = get_attr(attrs, "href")
                        self.content_links.append(link)

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
                        self.handle_post_end()
                        self.current_title = None
                        self.post_link = None
                        self.content_links = []

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
                self.current_title = data
                self.handle_post_title(data)


class LinkTextExtractor(SiteCrawler):
    def __init__(self, substrings_to_find: list[str], current_url: str):
        super().__init__(current_url)
        self.substrings_to_find = [s.upper() for s in substrings_to_find]
        self.matched_title = None

    def handle_post_end(self):
        if self.matched_title:
            print(f"""{self.current_url}, position {self.title_position}
{self.matched_title}
{self.post_link}
{newline.join(self.content_links)}""")

    def handle_post_title(self, data: str):
        data_upper = data.upper()
        for s in self.substrings_to_find:
            if s in data_upper:
                self.matched_title = data
                return
        # If no title match, reset
        self.matched_title = None


class SiteExporter(SiteCrawler):
    def __init__(self, current_url: str, out_file, last_poll, append_mode):
        super().__init__(current_url)
        self.last_poll = last_poll
        self.append_mode = append_mode
        self.out_file = out_file

    def handle_post_title(self, data: str):
        if self.is_done:
            return

    def handle_post_end(self):
        if self.is_done:
            return
        
        if self.content_links:
            linked_file = self.content_links[0].split("/")[-1]
            stripped_linked_file = linked_file.rstrip()
            if len(stripped_linked_file) != len(linked_file):
                logging.warning(f"Linked file name {linked_file} has trailing spaces, stripping to {stripped_linked_file}")
                linked_file = stripped_linked_file
        else:
            linked_file = "N/A"
            logging.error(f"No content links found for post: {self.current_title}")  

        if ";" in self.current_title:
            logging.warning(f"Title contains semicolon: {self.current_title}")
            
        out_line = f"{self.current_title};{self.post_link};{linked_file}"
        if out_line == self.last_poll:
            self.is_done = True
            logging.info(f"Reached last poll {self.current_title}")
            return
        self.out_file.write(out_line + newline)
        self.out_file.flush()


class CrawlerFactory:
    @abstractmethod
    def create_crawler(self):
        raise NotImplementedError()

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
    
class LinkTextExtractorFactory(CrawlerFactory):
    def __init__(self, keywords_file: str):
        self.keywords = read_keywords_from_file(keywords_file)

    def create_crawler(self, current_url: str):
        return LinkTextExtractor(self.keywords, current_url)

class SiteExporterFactory(CrawlerFactory):
    def __init__(self, export_to_file: str, action: str):
        self.append_mode = (action == "append")
        
        if os.path.exists(export_to_file):
            self.backup_path = export_to_file + ".bak"
            
            if os.path.exists(self.backup_path):
                raise Exception(f"Backup file {self.backup_path} already exists. Please remove it before proceeding.")
            
            with open(export_to_file, 'r', encoding="utf-8") as file:
                self.last_poll = file.readline().strip()

            shutil.move(export_to_file, export_to_file + ".bak")
        else:
            self.last_poll = None

        self.out_file = open(export_to_file, "w", encoding="utf-8")

    def create_crawler(self, current_url: str):
        return SiteExporter(current_url, self.out_file, self.last_poll, append_mode=self.append_mode)
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.out_file:
            with open(self.backup_path, 'r', encoding="utf-8") as backup_file:
                bak_content = backup_file.read()

            self.out_file.write(bak_content)
            self.out_file.close()

def read_keywords_from_file(filepath: str) -> list[str]:
    keywords = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            stripped_line = line.strip()
            if stripped_line:
                keywords.append(stripped_line)
    return keywords

def crawl_site(args, url_prefix: str, start_page: int = 0, end_page: int = 0):
    page_count = 0
    fail_pages = []

    match(args.action):
        case "search":
            if not args.keywords_file:
                raise ValueError("Keywords file must be specified for search action.")
            crawler_factory = LinkTextExtractorFactory(args.keywords_file)

        case "list" | "append":
            crawler_factory = SiteExporterFactory("db.csv", args.action)

    with crawler_factory:
        try:
            for i in range(start_page, end_page):
                page_url = f"{url_prefix}/{i}"
                success = False
                try:
                    msg = f"opening page {page_url}"
                    if i % 10 == 0:
                        logging.info(msg)
                    else:
                        logging.debug(msg)
                    with urllib.request.urlopen(page_url) as response:
                        html_content = response.read().decode('utf-8')
                        
                    parser = crawler_factory.create_crawler(current_url=page_url)
                    parser.feed(html_content)
                    success = True
                    if parser.is_done:
                        logging.info(f"Reached end of data for {page_url}, stopping further requests.")
                        break

                except urllib.error.URLError as e:
                    logging.error(f"Error visiting {page_url}: {e.reason}")
                except Exception as e:
                    logging.error(f"An unexpected error occurred for {page_url}: {e}")
                finally:
                    if success:                
                        page_count += 1
                    else:
                        fail_pages.append(i)

                # Wait for 10 seconds before the next request
                if i < end_page - 1:
                    logging.debug(f"Waiting for 10 seconds before visiting the next page...")
                    time.sleep(10)
        finally:
            logging.info(f"{page_count} pages crawled")
            if fail_pages:
                logging.info(f"{len(fail_pages)} pages failed: [{', '.join(map(str, fail_pages))}]")

    logging.info("Success")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Crawl web pages to find links containing specific keywords."
    )
    parser.add_argument(
        "--action",
        default="search",
        type=str,
    )
    parser.add_argument(
        "--keywords_file",
        type=str,
        default="keywords.txt",
    )
    parser.add_argument(
        "--url_prefix",
        type=str,
        default="https://example.com",
        help="prefix, no slash",
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
        default="info",
        choices=["debug", "info", "warning", "error", "critical"]
    )

    args = parser.parse_args()
    logging.basicConfig(level=logging._nameToLevel[args.log_level.upper()], format='[%(levelname)s]: %(message)s')
    crawl_site(args, args.url_prefix, args.start, args.end)
