import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re
from urllib.parse import urljoin, quote


class AkraParser:
    """Парсер сайта АКРА для поиска пресс-релизов о кредитных рейтингах."""
    
    BASE_URL = "https://acra-ratings.ru"
    SEARCH_URL = "https://acra-ratings.ru/press-releases/"
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
        })
        # Отключаем проверку SSL сертификатов (для обхода проблем с сертификатом сайта АКРА)
        self.session.verify = False
        # Подавляем предупреждения о небезопасном SSL
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    def search_company(self, company_name: str) -> list:
        """
        Поиск пресс-релизов по названию компании.
        
        Args:
            company_name: Название компании для поиска
            
        Returns:
            Список найденных пресс-релизов с информацией
        """
        # Формируем поисковый запрос
        search_url = f"{self.SEARCH_URL}?search={quote(company_name)}"
        
        try:
            response = self.session.get(search_url, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"Ошибка при запросе к сайту: {e}")
            return []
        
        soup = BeautifulSoup(response.text, 'lxml')
        results = []
        
        # Ищем элементы пресс-релизов
        # Структура может меняться, поэтому используем несколько селекторов
        press_releases = soup.find_all('a', href=re.compile(r'/press/releases/\d+'))
        
        for release in press_releases:
            title = release.get_text(strip=True)
            
            # Проверяем, упоминается ли компания в заголовке
            if company_name.lower() in title.lower():
                link = urljoin(self.BASE_URL, release['href'])
                
                # Пытаемся найти дату
                date = self._extract_date(release, link)
                
                results.append({
                    'title': title,
                    'link': link,
                    'date': date,
                    'company': company_name
                })
        
        # Если не нашли через поиск, пробуем просмотреть последние релизы
        if not results:
            results = self._scan_recent_releases(company_name)
        
        return results
    
    def _extract_date(self, element, link: str) -> str:
        """Извлечение даты из элемента или со страницы пресс-релиза."""
        # Пытаемся найти дату в соседних элементах
        parent = element.parent
        if parent:
            date_elem = parent.find(['time', 'span', 'div'], class_=re.compile(r'date|time|published', re.I))
            if date_elem:
                return date_elem.get_text(strip=True)
            
            # Ищем дату в формате ДД.ММ.ГГГГ
            text = parent.get_text()
            date_match = re.search(r'\d{2}\.\d{2}\.\d{4}', text)
            if date_match:
                return date_match.group()
        
        # Если не нашли, пробуем получить со страницы пресс-релиза
        return self._get_date_from_release_page(link)
    
    def _get_date_from_release_page(self, link: str) -> str:
        """Получение даты со страницы пресс-релиза."""
        try:
            response = self.session.get(link, timeout=10)
            response.raise_for_status()
        except requests.RequestException:
            return "Не удалось получить дату"
        
        soup = BeautifulSoup(response.text, 'lxml')
        
        # Ищем дату в различных местах
        date_patterns = [
            {'tag': 'time', 'attrs': {}},
            {'tag': 'span', 'attrs': {'class': re.compile(r'date|time|published', re.I)}},
            {'tag': 'div', 'attrs': {'class': re.compile(r'date|time|published', re.I)}},
        ]
        
        for pattern in date_patterns:
            elem = soup.find(pattern['tag'], pattern['attrs'])
            if elem:
                date_text = elem.get_text(strip=True)
                if re.match(r'\d{2}\.\d{2}\.\d{4}', date_text):
                    return date_text
        
        # Ищем дату в тексте страницы
        text = soup.get_text()
        date_match = re.search(r'\d{2}\.\d{2}\.\d{4}', text)
        if date_match:
            return date_match.group()
        
        return "Дата не найдена"
    
    def _scan_recent_releases(self, company_name: str, max_pages: int = 3) -> list:
        """Сканирование последних пресс-релизов, если поиск не дал результатов."""
        results = []
        
        for page in range(1, max_pages + 1):
            url = f"{self.SEARCH_URL}?PAGEN_1={page}" if page > 1 else self.SEARCH_URL
            
            try:
                response = self.session.get(url, timeout=10)
                response.raise_for_status()
            except requests.RequestException:
                continue
            
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Ищем все ссылки на пресс-релизы
            releases = soup.find_all('a', href=re.compile(r'/press/releases/\d+'))
            
            for release in releases:
                title = release.get_text(strip=True)
                
                if company_name.lower() in title.lower():
                    link = urljoin(self.BASE_URL, release['href'])
                    date = self._extract_date(release, link)
                    
                    results.append({
                        'title': title,
                        'link': link,
                        'date': date,
                        'company': company_name
                    })
            
            # Если нашли хотя бы один результат, прекращаем поиск
            if results:
                break
        
        return results
    
    def get_latest_rating_release(self, company_name: str) -> dict | None:
        """
        Получение последнего пресс-релиза о кредитном рейтинге для компании.
        
        Args:
            company_name: Название компании
            
        Returns:
            Словарь с информацией о пресс-релизе или None
        """
        results = self.search_company(company_name)
        
        if not results:
            return None
        
        # Сортируем по дате (если дата распознана) и возвращаем последний
        def parse_date(item):
            if item['date'] and re.match(r'\d{2}\.\d{2}\.\d{4}', item['date']):
                try:
                    return datetime.strptime(item['date'], '%d.%m.%Y')
                except ValueError:
                    pass
            return datetime.min
        
        sorted_results = sorted(results, key=parse_date, reverse=True)
        return sorted_results[0] if sorted_results else None


def main():
    """Основная функция для тестирования парсера."""
    parser = AkraParser()
    
    # Тестирование на компании "САМОЛЕТ"
    company = "САМОЛЕТ"
    print(f"Поиск пресс-релизов для компании: {company}")
    print("=" * 60)
    
    result = parser.get_latest_rating_release(company)
    
    if result:
        print("Найден актуальный пресс-релиз:")
        print(f"Заголовок: {result['title']}")
        print(f"Дата: {result['date']}")
        print(f"Ссылка: {result['link']}")
    else:
        print("Пресс-релизы не найдены.")
    
    print("\n" + "=" * 60)
    
    # Показать все найденные релизы
    all_results = parser.search_company(company)
    if all_results:
        print(f"\nВсе найденные пресс-релизы ({len(all_results)}):")
        for i, res in enumerate(all_results, 1):
            print(f"\n{i}. {res['title']}")
            print(f"   Дата: {res['date']}")
            print(f"   Ссылка: {res['link']}")


if __name__ == "__main__":
    main()