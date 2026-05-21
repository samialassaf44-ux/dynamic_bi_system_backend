from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import pandas as pd
import io
import os

app = FastAPI(title="Dynamic BI System Backend")

# CORS - Update with your actual Netlify URL after deployment
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change to your Netlify URL in production: ["https://your-site.netlify.app"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CURRENT_DF = None


def diagnose_column_type(series: pd.Series) -> str:
    if series.nunique() > len(series) / 2:
        return "unique_id"

    if pd.api.types.is_datetime64_any_dtype(series):
        return "date"

    if series.dtype == 'object':
        try:
            converted = pd.to_datetime(series, errors='coerce')
            if converted.notna().sum() / len(series) > 0.8:
                return "date"
        except:
            pass

    if pd.api.types.is_numeric_dtype(series):
        return "numeric"

    return "categorical"


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    global CURRENT_DF

    filename = file.filename
    if not (filename.endswith('.csv') or filename.endswith('.xlsx')):
        raise HTTPException(status_code=400, detail="امتداد الملف غير مدعوم. يرجى رفع ملف Excel أو CSV فقط.")

    try:
        contents = await file.read()

        if filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(contents))
        else:
            df = pd.read_excel(io.BytesIO(contents))

        CURRENT_DF = df

        columns_summary = []
        for col in df.columns:
            col_type = diagnose_column_type(df[col])

            sample_values = df[col].dropna().unique()[:3].tolist()
            sample_values = [str(v) for v in sample_values]

            columns_summary.append({
                "name": str(col),
                "type": col_type,
                "samples": sample_values
            })

        preview_data = df.head(5).fillna("").to_dict(orient="records")

        return {
            "status": "success",
            "filename": filename,
            "total_rows": len(df),
            "total_columns": len(df.columns),
            "columns": columns_summary,
            "preview": preview_data
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"حدث خطأ أثناء معالجة الملف: {str(e)}")


class ChartDataRequest(BaseModel):
    x_column: str
    y_column: Any = ""
    filters: Dict[str, Any]


@app.post("/api/chart-data")
async def get_chart_data(request: ChartDataRequest):
    global CURRENT_DF
    if CURRENT_DF is None:
        raise HTTPException(status_code=400, detail="لم يتم رفع أي ملف بيانات بعد.")

    try:
        filtered_df = CURRENT_DF.copy()

        for col, val in request.filters.items():
            if col in filtered_df.columns:
                filtered_df = filtered_df[filtered_df[col].astype(str) == str(val)]

        if filtered_df.empty:
            return {"x_data": [], "y_data": [], "series_name": str(request.x_column)}

        y_col = request.y_column
        if y_col is None or str(y_col).strip() == "" or str(y_col) == "null":
            y_col = None

        if y_col is None:
            counts = filtered_df[request.x_column].value_counts().head(15)
            return {
                "x_data": counts.index.astype(str).tolist(),
                "y_data": counts.values.tolist(),
                "series_name": str(request.x_column)
            }

        else:
            if y_col not in filtered_df.columns:
                raise HTTPException(status_code=400, detail=f"العمود الرقمي {y_col} غير موجود.")

            grouped = filtered_df.groupby(request.x_column)[y_col].mean().head(15)
            return {
                "x_data": grouped.index.astype(str).tolist(),
                "y_data": [round(float(v), 2) for v in grouped.values],
                "series_name": f"متوسط {y_col}"
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطأ أثناء معالجة البيانات إحصائياً: {str(e)}")


@app.get("/api/column-categories")
async def get_column_categories(column: str):
    global CURRENT_DF
    if CURRENT_DF is None:
        raise HTTPException(status_code=400, detail="لم يتم رفع ملف بعد.")

    if column not in CURRENT_DF.columns:
        raise HTTPException(status_code=400, detail="العمود المطلوب غير موجود.")

    categories = CURRENT_DF[column].dropna().unique().tolist()
    return {"categories": [str(cat) for cat in categories][:20]}


@app.get("/")
def read_root():
    return {"message": "FastAPI Server is running successfully!"}


class TableDataRequest(BaseModel):
    filters: Dict[str, Any]


@app.post("/api/table-data")
async def get_table_data(request: TableDataRequest):
    global CURRENT_DF
    if CURRENT_DF is None:
        raise HTTPException(status_code=400, detail="لم يتم رفع أي ملف بيانات بعد.")

    try:
        filtered_df = CURRENT_DF.copy()

        for col, val in request.filters.items():
            if col in filtered_df.columns:
                filtered_df = filtered_df[filtered_df[col].astype(str) == str(val)]

        preview_data = filtered_df.head(50).fillna("").to_dict(orient="records")

        return {
            "status": "success",
            "total_filtered_rows": len(filtered_df),
            "data": preview_data
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطأ أثناء جلب صفوف الجدول: {str(e)}")


# Railway needs this - listens on PORT from environment variable
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)