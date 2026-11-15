# aliexpress-bot

בוט טלגרם לחיפוש מוצרים ב-AliExpress, בעברית או באנגלית.

- חיפוש בעברית מתורגם לאנגלית (Google Translate, ו-ChatGPT כגיבוי) ונשלח ל-AliExpress Affiliate API.
- הבוט מסנן את התוצאות לפי רלוונטיות ומדרג אותן לפי רלוונטיות, מכירות ודירוג.
- הוא מחזיר את 5 המוצרים הטובים ביותר: אלבום תמונות, ולכל מוצר שם בעברית, מחיר, דירוג, כמות הזמנות וקישור שותפים.
- כפתורים מהירים: נעליים, שעון חכם, אקססוריז לטלפון ומוצרים חמים (`hotproduct.query`).

## מבנה

| קובץ | תפקיד |
|---|---|
| `main.py` | הפעלת הבוט, רישום ה-handlers ובדיקת משתני סביבה |
| `handlers/commands.py` | `/start`, `/help` |
| `handlers/messages.py` | טיפול בחיפוש: תרגום, קריאה ל-API, סינון, דירוג ושליחת התוצאות |
| `services/aliexpress_api.py` | חתימה וקריאות ל-AliExpress Affiliate API |
| `services/translation.py` | תרגום עם ספק מועדף וגיבוי |
| `services/logging.py` | לוג חיפושים |
| `services/utils.py` | התאמת מילים וציון רלוונטיות |

## הרצה מקומית

צריך Python 3.10 ומעלה.

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

יוצרים קובץ `.env` בתיקייה הראשית. הוא כבר ב-`.gitignore`:

```env
TOKEN=123456:telegram-bot-token
ALIEXPRESS_APP_KEY=...
ALIEXPRESS_APP_SECRET=...
ALI_TRACKING_ID=...
```

```bash
python main.py
```

## בדיקות

```bash
pip install pytest
python -m pytest tests
```

## פריסה ל-Railway

הפרויקט מוגדר כבר דרך `railway.json` ו-`Procfile` (worker שמריץ `python main.py`):

1. מחברים את הריפו לפרויקט חדש ב-Railway.
2. מגדירים את משתני הסביבה בלשונית **Variables** (לפחות `TOKEN`, `ALIEXPRESS_APP_KEY` ו-`ALIEXPRESS_APP_SECRET`).
3. פורסים. לוג של כל חיפוש מודפס כשורת `SEARCH_LOG: {...}` בלוגים של Railway.

## משתני סביבה

| משתנה | חובה | ברירת מחדל | תיאור |
|---|---|---|---|
| `TOKEN` | כן | – | הטוקן של בוט הטלגרם (מ-BotFather). בלעדיו הבוט לא עולה. |
| `ALIEXPRESS_APP_KEY` | כן | – | App Key של AliExpress Open Platform |
| `ALIEXPRESS_APP_SECRET` | כן | – | App Secret של AliExpress Open Platform |
| `ALI_TRACKING_ID` | מומלץ | – | Tracking ID של חשבון השותף. נשלח כ-`tracking_id` כדי לשייך את `promotion_link` לחשבון. |
| `OPENAI_API_KEY` | לא | – | מפתח OpenAI לתרגום גיבוי דרך ChatGPT |
| `OPENAI_MODEL` | לא | `gpt-4o` | המודל לתרגום דרך ChatGPT |
| `TRANSLATION_PROVIDER` | לא | `google` | ספק התרגום המועדף (`google` / `chatgpt`). הספק השני משמש רק אם הראשון נכשל. |
| `TRANSLATION_COMPARE_DEBUG` | לא | `0` | `1`: מריץ את כל ספקי התרגום על השאילתה ומכניס את ההשוואה ללוג |
| `ALI_TARGET_LANGUAGE` | לא | `EN` | שפת התוצאות מה-API |
| `ALI_TARGET_CURRENCY` | לא | `USD` | מטבע המחירים (`USD`, `ILS`, `EUR`, ...) |
| `ALI_SHIP_TO_COUNTRY` | לא | `US` | מדינת משלוח |
| `ALI_SORT_BY` | לא | – | מיון בחיפוש רגיל (למשל `LAST_VOLUME_DESC`) |
| `ALI_SEARCH_MODE` | לא | `hybrid` | `smartmatch`, `query`, או `hybrid` (קודם smartmatch, ואם אין תוצאות product.query) |
| `ALI_HOTPRODUCT_SORT` | לא | `LAST_VOLUME_DESC` | מיון במוצרים חמים |
| `ALI_PLATFORM_PRODUCT_TYPE` | לא | `ALL` | סוג מוצר במוצרים חמים |
| `ALI_CATEGORY_SHOES` | לא | – | מזהה קטגוריה לכפתור "נעליים" |
| `ALI_CATEGORY_SMARTWATCH` | לא | – | מזהה קטגוריה לכפתור "שעון חכם" |
| `ALI_CATEGORY_PHONE_ACCESSORIES` | לא | – | מזהה קטגוריה לכפתור "אקססוריז טלפון" |
| `ALI_COMPARE_SEARCH_DEBUG` | לא | `0` | `1`: מריץ גם smartmatch וגם product.query ומכניס את ההשוואה ללוג |
| `SEARCH_LOG_TO_FILE` | לא | `0` | `1`: כותב כל חיפוש גם לקובץ `search_log.txt`, בלי התשובה הגולמית מה-API |
