#!/usr/bin/env python3
"""
Parse Leeds Quranic Arabic Corpus (mustafa0x fork v0.4+corrections)
into BigQuery-ready CSV files.

Input:  quran-morphology.txt (tab-separated, 130K morpheme rows)
Output: quran_text.csv       (one row per word  — ~78K rows)
        leeds_morph.csv      (one row per morpheme — ~130K rows)

Format of input:
    surah:ayah:word:morpheme  TAB  arabic_form  TAB  pos_broad(N/V/P)  TAB  features(pipe-separated)
"""

import csv
import sys
import json
import os
from collections import OrderedDict

# ---------------------------------------------------------------------------
# Feature extraction helpers
# ---------------------------------------------------------------------------

def parse_features(feature_str):
    """Parse pipe-separated features into a structured dict."""
    result = {
        'pos_fine': None,       # fine-grained POS (e.g. PRON, REL, DEM, CONJ...)
        'root': None,           # Arabic root
        'lemma': None,          # lemma form
        'verb_form': None,      # VF:1-11 (Arabic verb forms / أبواب)
        'person': None,         # 1, 2, 3
        'gender': None,         # M, F
        'number': None,         # S, D, P
        'case_mood': None,      # NOM, ACC, GEN, IND, SUBJ, JUS
        'is_prefix': False,     # PREF marker
        'is_suffix': False,     # SUFF marker
        'is_definite': False,   # DET marker
        'is_indefinite': False, # INDEF marker
        'is_passive': False,    # PASS marker
        'aspect': None,         # PERF, IMPF, IMPV
        'noun_derivation': None,# ACT_PCPL, PASS_PCPL, VN
        'is_adj': False,        # ADJ marker
        'family': None,         # FAM: إِنّ / كان / كاد
        'extra_tags': [],       # anything else
    }

    if not feature_str or feature_str.strip() == '':
        return result

    tags = feature_str.strip().split('|')

    # POS fine-grained tags (appear as standalone tags)
    pos_tags = {
        'PN', 'PRON', 'DEM', 'REL', 'T', 'LOC', 'NV', 'COND', 'INTG',
        'P', 'CONJ', 'SUB', 'ACC', 'AMD', 'ANS', 'AVR', 'CAUS', 'CERT',
        'CIRC', 'COM', 'EQ', 'EXH', 'EXL', 'EXP', 'FUT', 'INC', 'INT',
        'NEG', 'PREV', 'PRO', 'REM', 'RES', 'RET', 'RSLT', 'SUP', 'SUR',
        'VOC', 'ATT', 'DIST', 'ADDR', 'INL', 'EMPH', 'IMPV', 'PRP', 'DET',
    }
    aspect_tags = {'PERF', 'IMPF'}  # IMPV can also be aspect for verbs
    derivation_tags = {'ACT_PCPL', 'PASS_PCPL', 'VN'}
    case_tags = {'NOM', 'ACC', 'GEN'}
    mood_tags = {'IND', 'SUBJ', 'JUS'}
    person_tags = {'1', '2', '3'}
    gender_tags = {'M', 'F'}
    number_tags = {'S', 'D', 'P'}

    for tag in tags:
        tag = tag.strip()
        if not tag:
            continue

        # Key:value tags
        if ':' in tag:
            key, val = tag.split(':', 1)
            if key == 'ROOT':
                result['root'] = val
            elif key == 'LEM':
                result['lemma'] = val
            elif key == 'VF':
                result['verb_form'] = int(val)
            elif key == 'MOOD':
                result['case_mood'] = val
            elif key == 'FAM':
                result['family'] = val
            else:
                result['extra_tags'].append(tag)
            continue

        # Standalone tags
        if tag == 'PREF':
            result['is_prefix'] = True
        elif tag == 'SUFF':
            result['is_suffix'] = True
        elif tag == 'DET':
            result['is_definite'] = True
        elif tag == 'INDEF':
            result['is_indefinite'] = True
        elif tag == 'PASS':
            result['is_passive'] = True
        elif tag == 'ADJ':
            result['is_adj'] = True
        elif tag in aspect_tags:
            result['aspect'] = tag
        elif tag == 'IMPV':
            # IMPV can be aspect (for verbs) or particle type
            # We'll handle this based on the broad POS category later
            result['aspect'] = tag
            result['pos_fine'] = tag
        elif tag in derivation_tags:
            result['noun_derivation'] = tag
        elif tag in case_tags:
            result['case_mood'] = tag
        elif tag in person_tags:
            result['person'] = int(tag)
        elif tag in gender_tags:
            result['gender'] = tag
        elif tag in number_tags:
            result['number'] = tag
        elif tag in pos_tags:
            result['pos_fine'] = tag
        else:
            # Combined person+gender+number like 2MS, 3MP, 1P, etc.
            parsed_pgn = parse_pgn(tag)
            if parsed_pgn:
                p, g, n = parsed_pgn
                if p:
                    result['person'] = p
                if g:
                    result['gender'] = g
                if n:
                    result['number'] = n
            else:
                result['extra_tags'].append(tag)

    result['extra_tags'] = '|'.join(result['extra_tags']) if result['extra_tags'] else None
    return result


def parse_pgn(tag):
    """Parse combined person/gender/number tags like 2MS, 3FP, 1P."""
    if not tag:
        return None

    person = None
    gender = None
    number = None
    i = 0

    if i < len(tag) and tag[i] in '123':
        person = int(tag[i])
        i += 1
    if i < len(tag) and tag[i] in 'MF':
        gender = tag[i]
        i += 1
    if i < len(tag) and tag[i] in 'SDP':
        number = tag[i]
        i += 1

    if i == len(tag) and (person or gender or number):
        return (person, gender, number)
    return None


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_morphology_file(input_path):
    """Parse quran-morphology.txt and return (words, morphemes) lists."""
    words = OrderedDict()  # key: (surah, ayah, word_idx) -> word info
    morphemes = []

    with open(input_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.rstrip('\n')
            if not line or line.startswith('#'):
                continue

            parts = line.split('\t')
            if len(parts) != 4:
                print(f"WARNING line {line_num}: expected 4 tab-separated fields, got {len(parts)}: {line[:80]}", file=sys.stderr)
                continue

            location, arabic_form, pos_broad, features = parts

            # Parse location
            loc_parts = location.split(':')
            if len(loc_parts) != 4:
                print(f"WARNING line {line_num}: bad location '{location}'", file=sys.stderr)
                continue

            surah = int(loc_parts[0])
            ayah = int(loc_parts[1])
            word_idx = int(loc_parts[2])
            morpheme_idx = int(loc_parts[3])

            # Parse features
            feat = parse_features(features)

            # Determine effective POS
            pos_fine = feat['pos_fine']
            if pos_broad == 'V' and feat['aspect'] == 'IMPV':
                pos_fine = None  # IMPV is aspect, not particle type

            # Build morpheme row
            morpheme = {
                'surah': surah,
                'ayah': ayah,
                'word_index': word_idx,
                'morpheme_index': morpheme_idx,
                'form_ar': arabic_form,
                'pos_broad': pos_broad,
                'pos_fine': pos_fine,
                'root': feat['root'],
                'lemma': feat['lemma'],
                'verb_form': feat['verb_form'],
                'aspect': feat['aspect'],
                'person': feat['person'],
                'gender': feat['gender'],
                'number': feat['number'],
                'case_mood': feat['case_mood'],
                'noun_derivation': feat['noun_derivation'],
                'is_prefix': feat['is_prefix'],
                'is_suffix': feat['is_suffix'],
                'is_definite': feat['is_definite'],
                'is_indefinite': feat['is_indefinite'],
                'is_passive': feat['is_passive'],
                'is_adj': feat['is_adj'],
                'family': feat['family'],
                'extra_tags': feat['extra_tags'],
            }
            morphemes.append(morpheme)

            # Accumulate word-level data
            word_key = (surah, ayah, word_idx)
            if word_key not in words:
                words[word_key] = {
                    'surah': surah,
                    'ayah': ayah,
                    'word_index': word_idx,
                    'fragments': [],
                    'root': None,
                    'lemma': None,
                    'pos_broad': None,
                }

            words[word_key]['fragments'].append(arabic_form)

            # The stem morpheme carries root/lemma/POS
            if not feat['is_prefix'] and not feat['is_suffix'] and not feat['is_definite']:
                if feat['root']:
                    words[word_key]['root'] = feat['root']
                if feat['lemma'] and feat['pos_fine'] != 'PRON':
                    words[word_key]['lemma'] = feat['lemma']
                if pos_broad in ('N', 'V'):
                    words[word_key]['pos_broad'] = pos_broad

    # Build quran_text rows
    word_rows = []
    for key, w in words.items():
        token = ''.join(w['fragments'])
        word_rows.append({
            'surah': w['surah'],
            'ayah': w['ayah'],
            'word_index': w['word_index'],
            'token_ar': token,
            'root': w['root'],
            'lemma': w['lemma'],
            'pos': w['pos_broad'],
        })

    return word_rows, morphemes


def write_csv(rows, fieldnames, output_path):
    """Write list of dicts to CSV."""
    with open(output_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            # Convert booleans to 0/1 for BigQuery
            clean = {}
            for k in fieldnames:
                v = row.get(k)
                if isinstance(v, bool):
                    clean[k] = 1 if v else 0
                elif v is None:
                    clean[k] = ''
                else:
                    clean[k] = v
            writer.writerow(clean)
    print(f"  Wrote {len(rows)} rows to {output_path}")


def write_schema(fieldnames, types, output_path):
    """Write BigQuery JSON schema."""
    schema = []
    for name in fieldnames:
        t = types.get(name, 'STRING')
        schema.append({
            'name': name,
            'type': t,
            'mode': 'NULLABLE',
        })
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
    print(f"  Wrote schema to {output_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.dirname(script_dir)
    leeds_dir = os.path.join(base_dir, 'leeds')

    input_path = sys.argv[1] if len(sys.argv) > 1 else '/tmp/quran-morphology/quran-morphology.txt'

    print(f"Parsing {input_path}...")
    word_rows, morphemes = parse_morphology_file(input_path)
    print(f"  Words:     {len(word_rows)}")
    print(f"  Morphemes: {len(morphemes)}")

    # --- quran_text ---
    text_fields = ['surah', 'ayah', 'word_index', 'token_ar', 'root', 'lemma', 'pos']
    text_types = {
        'surah': 'INTEGER', 'ayah': 'INTEGER', 'word_index': 'INTEGER',
        'token_ar': 'STRING', 'root': 'STRING', 'lemma': 'STRING', 'pos': 'STRING',
    }
    text_csv = os.path.join(leeds_dir, 'quran_text.csv')
    text_schema = os.path.join(leeds_dir, 'quran_text.schema.json')
    write_csv(word_rows, text_fields, text_csv)
    write_schema(text_fields, text_types, text_schema)

    # --- leeds_morph ---
    morph_fields = [
        'surah', 'ayah', 'word_index', 'morpheme_index',
        'form_ar', 'pos_broad', 'pos_fine',
        'root', 'lemma', 'verb_form', 'aspect',
        'person', 'gender', 'number', 'case_mood',
        'noun_derivation',
        'is_prefix', 'is_suffix', 'is_definite', 'is_indefinite',
        'is_passive', 'is_adj',
        'family', 'extra_tags',
    ]
    morph_types = {
        'surah': 'INTEGER', 'ayah': 'INTEGER',
        'word_index': 'INTEGER', 'morpheme_index': 'INTEGER',
        'form_ar': 'STRING', 'pos_broad': 'STRING', 'pos_fine': 'STRING',
        'root': 'STRING', 'lemma': 'STRING',
        'verb_form': 'INTEGER', 'aspect': 'STRING',
        'person': 'INTEGER', 'gender': 'STRING', 'number': 'STRING',
        'case_mood': 'STRING', 'noun_derivation': 'STRING',
        'is_prefix': 'BOOLEAN', 'is_suffix': 'BOOLEAN',
        'is_definite': 'BOOLEAN', 'is_indefinite': 'BOOLEAN',
        'is_passive': 'BOOLEAN', 'is_adj': 'BOOLEAN',
        'family': 'STRING', 'extra_tags': 'STRING',
    }
    morph_csv = os.path.join(leeds_dir, 'leeds_morph.csv')
    morph_schema = os.path.join(leeds_dir, 'leeds_morph.schema.json')
    write_csv(morphemes, morph_fields, morph_csv)
    write_schema(morph_fields, morph_types, morph_schema)

    # --- Summary stats ---
    print("\n=== Summary ===")
    surahs = set(w['surah'] for w in word_rows)
    print(f"  Surahs:    {len(surahs)} ({min(surahs)}-{max(surahs)})")
    roots = set(w['root'] for w in word_rows if w['root'])
    print(f"  Unique roots:  {len(roots)}")
    lemmas = set(w['lemma'] for w in word_rows if w['lemma'])
    print(f"  Unique lemmas: {len(lemmas)}")

    # POS distribution
    from collections import Counter
    pos_dist = Counter(m['pos_broad'] for m in morphemes)
    print(f"  POS distribution: {dict(pos_dist)}")
    fine_dist = Counter(m['pos_fine'] for m in morphemes if m['pos_fine'])
    print(f"  Top fine POS: {fine_dist.most_common(10)}")


if __name__ == '__main__':
    main()
