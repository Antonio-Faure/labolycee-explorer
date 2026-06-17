import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from urllib.parse import urljoin
import matplotlib.pyplot as plt
from datetime import datetime
import os
import csv
import json
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time
import warnings

# Ignorer le warning XML parsed as HTML
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

class RateLimiter:
    """Rate limiter to control request frequency"""
    def __init__(self, max_per_second=5):
        self.max_per_second = max_per_second
        self.min_interval = 1.0 / max_per_second
        self.last_request_time = 0
        self.lock = threading.Lock()
    
    def wait(self):
        with self.lock:
            current_time = time.time()
            time_since_last = current_time - self.last_request_time
            if time_since_last < self.min_interval:
                time.sleep(self.min_interval - time_since_last)
            self.last_request_time = time.time()


def extract_file_url(field_div):
    """Extract the best file URL (PDF preferred, then DOCX) from a Drupal file field."""
    # Try to get PDF from iframe data-src first
    iframe = field_div.find('iframe')
    if iframe and iframe.get('data-src'):
        src = iframe['data-src']
        if src.startswith('http'):
            return src
        # Handle protocol-relative URLs
        if src.startswith('//'):
            return 'https:' + src
        return urljoin('https://labolycee.org', src)

    # Fallback: get the first <a> link with .pdf or .docx
    for link in field_div.find_all('a', href=True):
        href = link['href']
        if href.endswith('.pdf') or href.endswith('.docx') or href.endswith('.doc'):
            if href.startswith('http'):
                return href
            if href.startswith('//'):
                return 'https:' + href
            return urljoin('https://labolycee.org', href)

    return ''


def is_exercice_page(soup):
    """Check if the page is a real exercise page (not a taxonomy/listing page)."""
    body = soup.find('body')
    if body and body.get('class'):
        classes = ' '.join(body.get('class'))
        if 'node--type-exercice' in classes:
            return True
    return False


def extract_pills_info(soup):
    """Extrait les infos des pills: header, points, thèmes, durée, sujet, corrigé"""
    result = {
        'header': None,
        'nb_points': None,
        'theme': [],
        'duree': None,
        'sujet_url': '',
        'correction_url': '',
        'is_valid': True  # Pour vérifier s'il n'y a pas de doublons
    }
    
    # Vérifier que la page est bien un exercice (et non une page de taxonomie)
    if not is_exercice_page(soup):
        result['is_valid'] = False
        return result
    
    # Header (h1) — sans guillemets
    header = soup.find('h1')
    if header:
        raw = header.get_text(strip=True)
        # Supprimer tous types de guillemets
        for ch in '\u201c\u201d\u2018\u2019\u00ab\u00bb"\'':
            raw = raw.replace(ch, '')
        result['header'] = raw.strip()
    
    # Points - vérifier qu'il n'y en a qu'un seul
    points_divs = soup.find_all('div', class_='field--name-field-points')
    if len(points_divs) == 1:
        item = points_divs[0].find('div', class_='field__item')
        if item:
            result['nb_points'] = item.get_text(strip=True)
    elif len(points_divs) > 1:
        result['is_valid'] = False  # Plus d'un champ de points trouvé
    
    # Thèmes - vérifier qu'il n'y a qu'un seul bloc de thèmes
    themes_divs = soup.find_all('div', class_='field--name-field-theme')
    if len(themes_divs) == 1:
        seen_themes = set()
        for link in themes_divs[0].find_all('a'):
            theme_text = link.get_text(strip=True)
            theme_text = theme_text.replace('"', '')
            if theme_text not in seen_themes:
                seen_themes.add(theme_text)
                result['theme'].append(theme_text)
    elif len(themes_divs) > 1:
        result['is_valid'] = False  # Plus d'un bloc de thèmes trouvé
    
    # Durée - vérifier qu'il n'y en a qu'une seule et extraire heures + minutes
    duree_divs = soup.find_all('div', class_='field--name-field-duree')
    if len(duree_divs) == 1:
        duree_parts = []
        
        # Extraire les heures
        heures = duree_divs[0].find('span', class_='hms__heures')
        if heures:
            heures_text = heures.get_text(strip=True)
            if heures_text:
                duree_parts.append(heures_text)
        
        # Extraire les minutes
        minutes = duree_divs[0].find('span', class_='hms__minutes')
        if minutes:
            minutes_text = minutes.get_text(strip=True)
            if minutes_text:
                duree_parts.append(minutes_text)
        
        # Combiner heures et minutes
        if duree_parts:
            result['duree'] = ' '.join(duree_parts)
    elif len(duree_divs) > 1:
        result['is_valid'] = False  # Plus d'une durée trouvée
    
    # Sujet (field--name-field-sujet)
    sujet_divs = soup.find_all('div', class_='field--name-field-sujet')
    if len(sujet_divs) == 1:
        result['sujet_url'] = extract_file_url(sujet_divs[0])
    elif len(sujet_divs) > 1:
        result['is_valid'] = False

    # Corrigé (field--name-field-corrige)
    corrige_divs = soup.find_all('div', class_='field--name-field-corrige')
    if len(corrige_divs) == 1:
        result['correction_url'] = extract_file_url(corrige_divs[0])
    elif len(corrige_divs) > 1:
        result['is_valid'] = False

    return result

def extract_urls(url, rate_limiter=None):
    """Extract all URLs from a given webpage."""
    try:
        if rate_limiter:
            rate_limiter.wait()
        
        headers = {
            'User-Agent': 'PersonalCrawlerBot/1.0 (Educational purposes; respects robots.txt)'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        urls = []
        for link in soup.find_all('a', href=True):
            href = link['href']
            absolute_url = urljoin(url, href)
            urls.append(absolute_url)

        return urls, soup

    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return [], None

def filter_site_urls(base_url, url_list):
    """Filter URLs to only include those belonging to the same site."""
    site_urls = []
    base_url_length = len(base_url)
    
    for url in url_list:
        # Exclure les URLs XML
        if url.endswith('.xml'):
            continue
        
        if (url.startswith(base_url) and 
            len(url) > base_url_length and 
            '#' not in url):
            site_urls.append(url)
    
    return site_urls

def save_urls_to_file(urls, base_url, output_dir='.'):
    """Save URLs to a text file."""
    os.makedirs(output_dir, exist_ok=True)
    filename = base_url.replace('https://', '').replace('http://', '').rstrip('/')
    filepath = os.path.join(output_dir, f"{filename}.txt")
    
    with open(filepath, 'w', encoding='utf-8') as file:
        for url in sorted(urls):
            file.write(f"{url}\n")
    
    print(f"URLs saved to {filepath}")

def plot_crawl_progress(progress_data, base_url, output_dir='.'):
    """Plot the crawling progress and save the graph."""
    os.makedirs(output_dir, exist_ok=True)
    filename = base_url.replace('https://', '').replace('http://', '').rstrip('/')
    
    # Créer deux subplots: un pour les URLs et exercices, un pour le ratio
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 10))
    steps = list(range(1, len(progress_data) + 1))
    
    # Extract visited, discovered, and exercises counts from tuples
    visited_counts = [data[0] for data in progress_data]
    discovered_counts = [data[1] for data in progress_data]
    exercises_counts = [data[2] for data in progress_data]
    
    # Calculate ratio (visited / discovered)
    ratios = [visited / discovered if discovered > 0 else 0 
              for visited, discovered in zip(visited_counts, discovered_counts)]
    
    # Premier graphique: URLs et exercices
    ax1.plot(steps, discovered_counts, color="b", marker='o', label="URLs discovered", linewidth=2)
    ax1.plot(steps, visited_counts, color="r", marker='s', label="URLs visited", linewidth=2)
    ax1.plot(steps, exercises_counts, color="g", marker='^', label="Exercises found", linewidth=2)
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    ax1.set_xlabel("Batch number")
    ax1.set_ylabel("Number of URLs/Exercises")
    ax1.set_title("Web Crawling Progress")
    
    # Deuxième graphique: Ratio visited/discovered
    ax2.plot(steps, ratios, color="purple", marker='d', label="Ratio (visited/discovered)", linewidth=2)
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    ax2.set_xlabel("Batch number")
    ax2.set_ylabel("Ratio")
    ax2.set_title("Crawling Efficiency (Visited/Discovered)")
    ax2.set_ylim([0, 1.1])  # Le ratio est entre 0 et 1
    
    plt.tight_layout()
    plot_path = os.path.join(output_dir, f"{filename}.png")
    plt.savefig(plot_path)
    print(f"Plot saved to {plot_path}")
    plt.close()

def save_exercises_to_csv(exercises_data, base_url, output_dir='.'):
    """Save exercise data to a CSV file (with sujet and correction URLs)."""
    os.makedirs(output_dir, exist_ok=True)
    filename = base_url.replace('https://', '').replace('http://', '').rstrip('/')
    filepath = os.path.join(output_dir, f"{filename}_exercises.csv")
    
    with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['header', 'url', 'nb_points', 'theme', 'duree', 'sujet_url', 'correction_url']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter=';')
        
        writer.writeheader()
        
        for exercise in exercises_data:
            theme_str = ' | '.join(exercise['theme']) if exercise['theme'] else ''
            
            writer.writerow({
                'header': exercise['header'] or '',
                'url': exercise['url'],
                'nb_points': exercise['nb_points'] or '',
                'theme': theme_str,
                'duree': exercise['duree'] or '',
                'sujet_url': exercise.get('sujet_url', ''),
                'correction_url': exercise.get('correction_url', '')
            })
    
    print(f"Exercise data saved to {filepath}")
    return filepath


def save_exercises_to_json(exercises_data, filepath):
    """Save exercise data to a JSON file."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(exercises_data, f, ensure_ascii=False, indent=2)
    print(f"Exercise data saved to {filepath}")

def process_url(url, start_url, rate_limiter):
    """Process a single URL and return found URLs and exercise data."""
    page_urls, soup = extract_urls(url, rate_limiter)
    
    exercise_data = None
    if soup:
        pills_info = extract_pills_info(soup)
        
        # Vérifications pour qu'une page soit considérée comme un exercice:
        # 1. Tous les champs requis doivent être présents
        # 2. L'URL ne doit pas contenir "?"
        # 3. Les données doivent être valides (pas de doublons de champs)
        if (pills_info['nb_points'] and 
            pills_info['theme'] and 
            pills_info['duree'] and 
            '?' not in url and
            '/sujets-bac' not in url and
            pills_info['is_valid']):
            exercise_data = {
                'header': pills_info['header'],
                'url': url,
                'nb_points': pills_info['nb_points'],
                'theme': pills_info['theme'],
                'duree': pills_info['duree'],
                'sujet_url': pills_info.get('sujet_url', ''),
                'correction_url': pills_info.get('correction_url', '')
            }
    
    # Filter URLs
    filtered_urls = filter_site_urls(start_url, page_urls)
    
    return filtered_urls, exercise_data

def crawl_website(start_url, max_urls=10000, max_workers=5, max_requests_per_second=5):
    """Crawl a website in parallel and extract exercise information."""
    # Initialize
    site_urls = [start_url]
    visited_urls = set()
    exercises_data = []
    progress_data = []
    rate_limiter = RateLimiter(max_per_second=max_requests_per_second)
    lock = threading.Lock()
    
    print(f"Starting parallel crawl from: {start_url}")
    print(f"Max workers: {max_workers}, Max requests/sec: {max_requests_per_second}")
    
    while len(visited_urls) < len(site_urls) and len(site_urls) <= max_urls:
        # Get batch of URLs to process
        with lock:
            urls_to_process = [url for url in site_urls if url not in visited_urls]
            batch_size = min(max_workers * 3, len(urls_to_process))
            batch = urls_to_process[:batch_size]
        
        if not batch:
            break
        
        print(f"\nProcessing batch of {len(batch)} URLs...")
        print(f"Progress: {len(visited_urls)}/{len(site_urls)} visited, {len(exercises_data)} exercises found")
        
        # Process URLs in parallel
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_url = {
                executor.submit(process_url, url, start_url, rate_limiter): url 
                for url in batch
            }
            
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                
                with lock:
                    visited_urls.add(url)
                
                try:
                    filtered_urls, exercise_data = future.result()
                    
                    # Add exercise data if found
                    if exercise_data:
                        with lock:
                            exercises_data.append(exercise_data)
                        print(f"  [+] Exercise: {exercise_data['nb_points']} - {url}")
                    
                    # Add new URLs
                    new_urls = 0
                    with lock:
                        for new_url in filtered_urls:
                            if new_url not in site_urls:
                                site_urls.append(new_url)
                                new_urls += 1
                    
                    if new_urls > 0:
                        print(f"  + {new_urls} new URLs from {url}")
                
                except Exception as e:
                    print(f"  [!] Error processing {url}: {e}")
        
        with lock:
            progress_data.append((len(visited_urls), len(site_urls), len(exercises_data)))
    
    return site_urls, progress_data, exercises_data

# ── Version Management ─────────────────────────────────────────────

DATA_DIR = 'data'

def get_version_timestamp():
    return datetime.now().strftime('%Y-%m-%d_%H-%M-%S')

def get_version_dir(timestamp):
    return os.path.join(DATA_DIR, f'v_{timestamp}')

def load_versions_manifest():
    manifest_path = os.path.join(DATA_DIR, 'versions.json')
    if os.path.exists(manifest_path):
        with open(manifest_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'versions': []}

def save_versions_manifest(manifest):
    os.makedirs(DATA_DIR, exist_ok=True)
    manifest_path = os.path.join(DATA_DIR, 'versions.json')
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

def load_exercises_from_json(filepath):
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def compute_stats(exercises_data):
    total = len(exercises_data)
    with_sujet = sum(1 for ex in exercises_data if ex.get('sujet_url'))
    with_correction = sum(1 for ex in exercises_data if ex.get('correction_url'))
    return {
        'exercises_count': total,
        'with_sujet': with_sujet,
        'with_correction': with_correction,
        'coverage_rate': round(with_correction / total, 4) if total > 0 else 0
    }

def compute_diff(old_exercises, new_exercises):
    old_urls = {ex['url'] for ex in old_exercises}
    new_urls = {ex['url'] for ex in new_exercises}

    old_by_url = {ex['url']: ex for ex in old_exercises}
    new_by_url = {ex['url']: ex for ex in new_exercises}

    added = [ex for ex in new_exercises if ex['url'] not in old_urls]
    removed = [ex for ex in old_exercises if ex['url'] not in new_urls]

    changed = []
    for url in old_urls & new_urls:
        old_ex = old_by_url[url]
        new_ex = new_by_url[url]
        if (old_ex.get('nb_points') != new_ex.get('nb_points') or
            old_ex.get('theme') != new_ex.get('theme') or
            old_ex.get('duree') != new_ex.get('duree') or
            old_ex.get('sujet_url') != new_ex.get('sujet_url') or
            old_ex.get('correction_url') != new_ex.get('correction_url')):
            changed.append({
                'url': url,
                'header': new_ex.get('header', ''),
                'old': {k: old_ex.get(k, '') for k in ['nb_points', 'theme', 'duree', 'sujet_url', 'correction_url']},
                'new': {k: new_ex.get(k, '') for k in ['nb_points', 'theme', 'duree', 'sujet_url', 'correction_url']}
            })

    return {
        'added_count': len(added),
        'removed_count': len(removed),
        'changed_count': len(changed),
        'added': [{'url': ex['url'], 'header': ex.get('header', '')} for ex in added],
        'removed': [{'url': ex['url'], 'header': ex.get('header', '')} for ex in removed],
        'changed': changed
    }

def save_version_snapshot(site_urls, exercises_data, progress_data, base_url, crawl_duration):
    timestamp = get_version_timestamp()
    version_dir = get_version_dir(timestamp)
    os.makedirs(version_dir, exist_ok=True)

    urls_path = os.path.join(version_dir, 'urls.txt')
    with open(urls_path, 'w', encoding='utf-8') as f:
        for url in sorted(site_urls):
            f.write(f"{url}\n")

    csv_path = save_exercises_to_csv(exercises_data, base_url, output_dir=version_dir)

    json_path = os.path.join(version_dir, 'exercises.json')
    save_exercises_to_json(exercises_data, json_path)

    plot_crawl_progress(progress_data, base_url, output_dir=version_dir)

    stats = compute_stats(exercises_data)
    stats['timestamp'] = timestamp
    stats['datetime'] = datetime.now().isoformat()
    stats['urls_count'] = len(site_urls)
    stats['crawl_duration_seconds'] = crawl_duration

    manifest = load_versions_manifest()
    prev_version = manifest['versions'][-1] if manifest['versions'] else None

    diff = None
    if prev_version:
        prev_json_path = os.path.join(get_version_dir(prev_version['timestamp']), 'exercises.json')
        prev_exercises = load_exercises_from_json(prev_json_path)
        diff = compute_diff(prev_exercises, exercises_data)

        diff_path = os.path.join(version_dir, 'diff.json')
        with open(diff_path, 'w', encoding='utf-8') as f:
            json.dump(diff, f, ensure_ascii=False, indent=2)
        print(f"Diff saved to {diff_path}")
        print(f"  Added: {diff['added_count']}, Removed: {diff['removed_count']}, Changed: {diff['changed_count']}")

    manifest['versions'].append(stats)
    save_versions_manifest(manifest)

    # Generate graphs
    graphs_dir = os.path.join(version_dir, 'graphs')
    os.makedirs(graphs_dir, exist_ok=True)

    plot_evolution(manifest, graphs_dir)
    plot_added_removed(manifest, graphs_dir)
    plot_distribution(exercises_data, 'theme', 'Répartition par thème (top 15)', graphs_dir, 'distribution_themes.png')
    plot_distribution(exercises_data, 'nb_points', 'Répartition par nombre de points', graphs_dir, 'distribution_points.png')

    # Update latest directory
    latest_dir = os.path.join(DATA_DIR, 'latest')
    if os.path.exists(latest_dir):
        shutil.rmtree(latest_dir)
    shutil.copytree(version_dir, latest_dir)

    # Update root CSV for backward compatibility
    root_csv = f"{base_url.replace('https://', '').replace('http://', '').rstrip('/')}_exercises.csv"
    shutil.copy2(csv_path, root_csv)

    return version_dir, stats, diff


# ── Graph Generation ───────────────────────────────────────────────

def plot_evolution(manifest, output_dir):
    versions = manifest['versions']
    if len(versions) < 1:
        return

    labels = [v['timestamp'][:10] for v in versions]
    counts = [v['exercises_count'] for v in versions]
    coverage = [v['coverage_rate'] * 100 for v in versions]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))

    colors = plt.cm.Blues([0.4 + 0.5 * i / max(len(versions), 1) for i in range(len(versions))])

    ax1.bar(labels, counts, color=colors, edgecolor='#1a73e8', linewidth=1.2)
    ax1.set_ylabel("Nombre d'exercices")
    ax1.set_title('Évolution du nombre d\'exercices')
    ax1.tick_params(axis='x', rotation=45)
    ax1.grid(True, alpha=0.3, axis='y')

    for i, v in enumerate(counts):
        ax1.text(i, v + max(counts) * 0.01, str(v), ha='center', fontweight='bold')

    ax2.plot(labels, coverage, color='#2ecc71', marker='o', linewidth=2, markersize=8)
    ax2.set_ylabel('Taux de couverture (%)')
    ax2.set_title("Taux d'exercices avec corrigé")
    ax2.tick_params(axis='x', rotation=45)
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim([0, 100])

    for i, v in enumerate(coverage):
        ax2.text(i, v + 1, f'{v:.1f}%', ha='center', fontweight='bold')

    plt.tight_layout()
    path = os.path.join(output_dir, 'evolution_exercices.png')
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"Evolution plot saved to {path}")

def plot_added_removed(manifest, output_dir):
    versions = manifest['versions']
    if len(versions) < 2:
        return

    added = []
    removed = []
    labels = []

    for v in versions[1:]:
        diff_path = os.path.join(get_version_dir(v['timestamp']), 'diff.json')
        if os.path.exists(diff_path):
            with open(diff_path, 'r', encoding='utf-8') as f:
                diff = json.load(f)
            added.append(diff['added_count'])
            removed.append(diff['removed_count'])
            labels.append(v['timestamp'][:10])

    if not labels:
        return

    fig, ax = plt.subplots(figsize=(10, 6))
    x = range(len(labels))
    width = 0.35

    ax.bar([i - width/2 for i in x], added, width, label='Ajoutés', color='#2ecc71', edgecolor='#27ae60')
    ax.bar([i + width/2 for i in x], removed, width, label='Supprimés', color='#e74c3c', edgecolor='#c0392b')

    ax.set_xlabel('Version')
    ax.set_ylabel("Nombre d'exercices")
    ax.set_title('Exercices ajoutés et supprimés par version')
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=45)
    ax.legend()
    ax.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    path = os.path.join(output_dir, 'ajouts_suppressions.png')
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"Added/removed plot saved to {path}")

def plot_distribution(exercises_data, key, title, output_dir, filename):
    if not exercises_data:
        return

    values = []
    for ex in exercises_data:
        val = ex.get(key, '')
        if isinstance(val, list):
            values.extend(val)
        elif val:
            values.append(str(val))

    if not values:
        return

    from collections import Counter
    counter = Counter(values)
    items = counter.most_common(15)

    fig, ax = plt.subplots(figsize=(12, 6))
    labels = [item[0] if len(item[0]) < 40 else item[0][:37] + '...' for item in items]
    counts = [item[1] for item in items]
    colors = plt.cm.Set2([i / max(len(items), 1) for i in range(len(items))])

    bars = ax.barh(range(len(items)), counts, color=colors, edgecolor='gray', linewidth=0.5)
    ax.set_yticks(range(len(items)))
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Nombre d'exercices")
    ax.set_title(title)
    ax.grid(True, alpha=0.3, axis='x')

    for bar, count in zip(bars, counts):
        ax.text(bar.get_width() + max(counts) * 0.01, bar.get_y() + bar.get_height()/2,
                str(count), va='center', fontweight='bold', fontsize=9)

    plt.tight_layout()
    path = os.path.join(output_dir, filename)
    plt.savefig(path, dpi=150)
    plt.close()
    print(f"Distribution plot saved to {path}")


# ── Main ───────────────────────────────────────────────────────────

def main():
    start_time = datetime.now()
    start_url = "https://labolycee.org/"
    
    MAX_WORKERS = 5
    MAX_REQUESTS_PER_SEC = 5
    MAX_URLS = 10000
    
    print("=" * 60)
    print("PARALLEL WEBSITE CRAWLER WITH EXERCISE EXTRACTION")
    print("=" * 60)
    print(f"Configuration:")
    print(f"  - Max workers: {MAX_WORKERS}")
    print(f"  - Max requests/sec: {MAX_REQUESTS_PER_SEC}")
    print(f"  - Max URLs: {MAX_URLS}")
    print("=" * 60)
    
    try:
        site_urls, progress_data, exercises_data = crawl_website(
            start_url, 
            max_urls=MAX_URLS,
            max_workers=MAX_WORKERS,
            max_requests_per_second=MAX_REQUESTS_PER_SEC
        )
        
        site_urls.sort()
        
        end_time = datetime.now()
        duration = end_time - start_time
        crawl_duration_seconds = int(duration.total_seconds())
        
        # Also save to root for immediate access
        save_urls_to_file(site_urls, start_url)
        csv_path = save_exercises_to_csv(exercises_data, start_url)
        plot_crawl_progress(progress_data, start_url)
        
        # Save versioned snapshot with all indicators
        version_dir, stats, diff = save_version_snapshot(
            site_urls, exercises_data, progress_data, start_url, crawl_duration_seconds
        )
        
        print(f"\n{'=' * 60}")
        print(f"Total URLs found: {len(site_urls)}")
        print(f"Total exercises found: {len(exercises_data)}")
        print(f"  - With sujet PDF: {stats['with_sujet']}")
        print(f"  - With correction PDF: {stats['with_correction']}")
        print(f"  - Coverage rate: {stats['coverage_rate'] * 100:.1f}%")
        print(f"CSV file: {csv_path}")
        print(f"Version snapshot: {version_dir}")
        if diff:
            print(f"  - Added: {diff['added_count']}, Removed: {diff['removed_count']}, Changed: {diff['changed_count']}")
        print(f"Total crawling time: {duration}")
        print("=" * 60)
        
    except Exception as e:
        print(f"An error occurred during crawling: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()