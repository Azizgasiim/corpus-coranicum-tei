-- ============================================================================
-- BigQuery: Load Leeds Quranic Arabic Corpus
-- Source: mustafa0x/quran-morphology (fork of Kais Dukes' QAC v0.4)
-- ============================================================================

-- 1. Create dataset
-- bq mk --dataset quran

-- 2. Load quran_text (reference table — one row per word)
-- bq load --source_format=CSV --skip_leading_rows=1 \
--   --schema=quran_text.schema.json \
--   quran.quran_text quran_text.csv

-- 3. Load leeds_morph (morpheme-level annotations)
-- bq load --source_format=CSV --skip_leading_rows=1 \
--   --schema=leeds_morph.schema.json \
--   quran.leeds_morph leeds_morph.csv

-- ============================================================================
-- Example Queries
-- ============================================================================

-- === 1. البحث عن كلمة بالجذر ===
-- Find all words with root ر-ح-م (mercy)
SELECT surah, ayah, word_index, token_ar, lemma
FROM quran.quran_text
WHERE root = 'رحم'
ORDER BY surah, ayah, word_index;

-- === 2. توزيع الأبواب (verb forms) ===
-- Distribution of Arabic verb forms (أبواب الفعل)
SELECT
  verb_form,
  CASE verb_form
    WHEN 1 THEN 'فَعَلَ'
    WHEN 2 THEN 'فَعَّلَ'
    WHEN 3 THEN 'فاعَلَ'
    WHEN 4 THEN 'أَفْعَلَ'
    WHEN 5 THEN 'تَفَعَّلَ'
    WHEN 6 THEN 'تَفاعَلَ'
    WHEN 7 THEN 'انْفَعَلَ'
    WHEN 8 THEN 'افْتَعَلَ'
    WHEN 9 THEN 'افْعَلَّ'
    WHEN 10 THEN 'اسْتَفْعَلَ'
  END AS verb_form_ar,
  COUNT(*) AS count
FROM quran.leeds_morph
WHERE pos_broad = 'V' AND verb_form IS NOT NULL
GROUP BY verb_form
ORDER BY count DESC;

-- === 3. أكثر الجذور تكراراً ===
-- Most frequent roots
SELECT root, COUNT(*) AS word_count
FROM quran.quran_text
WHERE root IS NOT NULL AND root != ''
GROUP BY root
ORDER BY word_count DESC
LIMIT 20;

-- === 4. تحليل صرفي كامل لآية ===
-- Full morphological breakdown of Ayat al-Kursi (2:255)
SELECT
  t.word_index,
  t.token_ar,
  m.morpheme_index,
  m.form_ar,
  m.pos_broad,
  m.pos_fine,
  m.root,
  m.lemma,
  m.aspect,
  m.verb_form,
  m.person,
  m.gender,
  m.number,
  m.case_mood
FROM quran.quran_text t
JOIN quran.leeds_morph m
  ON t.surah = m.surah AND t.ayah = m.ayah AND t.word_index = m.word_index
WHERE t.surah = 2 AND t.ayah = 255
ORDER BY t.word_index, m.morpheme_index;

-- === 5. الأفعال حسب الزمن والصيغة ===
-- Verb tense × voice distribution
SELECT
  aspect,
  CASE aspect
    WHEN 'PERF' THEN 'ماضٍ'
    WHEN 'IMPF' THEN 'مضارع'
    WHEN 'IMPV' THEN 'أمر'
  END AS aspect_ar,
  is_passive,
  COUNT(*) AS count
FROM quran.leeds_morph
WHERE pos_broad = 'V'
GROUP BY aspect, is_passive
ORDER BY count DESC;

-- === 6. اسم الفاعل واسم المفعول ===
-- Active/passive participles
SELECT
  noun_derivation,
  CASE noun_derivation
    WHEN 'ACT_PCPL' THEN 'اسم فاعل'
    WHEN 'PASS_PCPL' THEN 'اسم مفعول'
    WHEN 'VN' THEN 'مصدر'
  END AS type_ar,
  COUNT(*) AS count
FROM quran.leeds_morph
WHERE noun_derivation IS NOT NULL
GROUP BY noun_derivation
ORDER BY count DESC;

-- === 7. الكلمات الفريدة في سورة ===
-- Words unique to a specific surah (hapax legomena per surah)
WITH word_surah_count AS (
  SELECT lemma, COUNT(DISTINCT surah) AS surah_count
  FROM quran.quran_text
  WHERE lemma IS NOT NULL AND lemma != ''
  GROUP BY lemma
)
SELECT t.surah, t.ayah, t.word_index, t.token_ar, t.lemma, t.root
FROM quran.quran_text t
JOIN word_surah_count w ON t.lemma = w.lemma
WHERE w.surah_count = 1
ORDER BY t.surah, t.ayah, t.word_index;

-- === 8. VIEW: quran_enriched — كل المعلومات عن كل كلمة ===
CREATE OR REPLACE VIEW quran.quran_enriched AS
SELECT
  t.surah,
  t.ayah,
  t.word_index,
  t.token_ar,
  t.root,
  t.lemma,
  t.pos,
  -- Aggregate morpheme-level info
  STRING_AGG(m.form_ar, '' ORDER BY m.morpheme_index) AS reconstructed,
  STRING_AGG(
    CONCAT(m.pos_broad, COALESCE(CONCAT(':', m.pos_fine), '')),
    '+'
    ORDER BY m.morpheme_index
  ) AS morpheme_chain,
  MAX(m.verb_form) AS verb_form,
  MAX(m.aspect) AS aspect,
  MAX(m.noun_derivation) AS noun_derivation,
  MAX(CASE WHEN m.pos_broad IN ('N','V') AND NOT m.is_prefix AND NOT m.is_suffix
      THEN m.case_mood END) AS case_mood,
  COUNTIF(m.is_prefix) AS prefix_count,
  COUNTIF(m.is_suffix) AS suffix_count,
FROM quran.quran_text t
LEFT JOIN quran.leeds_morph m
  ON t.surah = m.surah AND t.ayah = m.ayah AND t.word_index = m.word_index
GROUP BY t.surah, t.ayah, t.word_index, t.token_ar, t.root, t.lemma, t.pos;
