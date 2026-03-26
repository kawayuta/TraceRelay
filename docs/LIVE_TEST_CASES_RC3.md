# RC3 Live Test Cases

## 1. Organization expansion
Prompt:
`Googleの事業内容に加えて、主要経営陣、主要子会社、主要買収案件、主要競合、主要リスク、地域別展開も構造化して整理して`

Expected:
- family: `organization`
- likely schema evolution needed

## 2. Media expansion
Prompt:
`Macrossについて、作品概要だけでなく、主要シリーズ一覧、視聴順、時系列順、主要キャラクター、主要メカ、主要楽曲、制作スタッフを構造化して`

Expected:
- family: `media_work`
- likely schema evolution or re-extract path

## 3. Policy bootstrap
Prompt:
`日本の少子化対策の政策パッケージを、政策目的、対象人口、実施主体、施策一覧、財源、評価指標、論点で構造化して`

Expected:
- family: `policy`
- family bootstrap if absent

## 4. Incident bootstrap
Prompt:
`このAPI障害について、影響範囲、原因仮説、依存サービス、時系列、再発防止策を構造化して`

Expected:
- family: `system_incident`
- family bootstrap if absent

## 5. Relationship bootstrap
Prompt:
`TSMCとNVIDIAの関係を、供給関係、製品カテゴリ、依存度、主要リスク、代替可能性で整理して`

Expected:
- family: `relationship` or `supply_chain_relation`
- not a single-entity `organization` fallback
