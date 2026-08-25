# ייבוא קטלוג המוצרים של MDL

התיקייה הזאת היא כלי ייבוא חד־פעמי ואינה מודול Odoo. אין בה קובץ
`__manifest__.py`, היא אינה מופיעה ב־Apps והיא אינה מריצה דבר באופן אוטומטי.

הכלי שומר את נתוני הקטלוג מחוץ למודול `mdl_product_catalog` ומייבא אותם
כרשומות רגילות למסד הנתונים. לאחר הייבוא ממשיכים לנהל את הקטלוג מתוך Odoo.

## לפני ההרצה

1. יש לגבות את מסד הנתונים.
2. יש להתקין או לשדרג את `mdl_product_catalog` לגרסה המתאימה.
3. יש להריץ תחילה ב־Staging שמבוסס על עותק עדכני של Production.
4. אין להתקין את המודול הישן `mdl_product_catalog_test_data`.

אם המודול הישן כבר יצר את הקטלוג במסד בדיקות, הסקריפט מזהה את המזהים
הישנים, מעביר אותם למרחב המזהים של הסקריפט ומוודא שכל המק״טים קיימים.

## בדיקה ללא שמירה

מתוך Shell של ה־Build, בתיקיית `src/user`:

```bash
MDL_CATALOG_MODE=check odoo-bin shell < scripts/mdl_product_catalog_import/import_catalog.py
```

זהו מצב ברירת המחדל. הסקריפט מריץ את כל הייבוא והבדיקות בתוך טרנזקציה
ולבסוף מבצע Rollback, כך ששום רשומה אינה נשמרת.

## ייבוא ושמירה

רק לאחר שמצב הבדיקה הסתיים ללא שגיאה:

```bash
MDL_CATALOG_MODE=apply odoo-bin shell < scripts/mdl_product_catalog_import/import_catalog.py
```

במצב `apply` מתבצע Commit רק לאחר שכל הפריטים, המק״טים והשילובים עברו
אימות. במקרה של שגיאה מתבצע Rollback מלא.

הסקריפט בטוח להרצה חוזרת: הוא משתמש ב־External IDs קבועים, ובמקום ליצור
כפילויות הוא מאמת שהקטלוג שכבר יובא שלם.

## בדיקת קובץ המקור ללא Odoo

```bash
python3 scripts/mdl_product_catalog_import/qa_catalog.py \
  scripts/mdl_product_catalog_import/catalog.json
```

התוצאה הצפויה כוללת 56 תבניות, 15 מאפיינים, 92 ערכים ו־1,274 פריטים.
