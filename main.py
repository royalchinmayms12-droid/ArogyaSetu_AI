import os, sqlite3, secrets, hashlib, hmac, json
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager
from typing import Literal
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, constr

load_dotenv(Path(__file__).with_name(".env"), override=False)
app = FastAPI(title="ArogyaSetu AI API", version="2.0.0")
origins = [x.strip() for x in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False, allow_methods=["GET","POST","PATCH"], allow_headers=["Content-Type","Authorization"])
DB_PATH = Path(__file__).with_name("arogyasetu.db")

@contextmanager
def db():
    conn=sqlite3.connect(DB_PATH)
    conn.row_factory=sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('patient','hospital')),
          facility TEXT DEFAULT '', share_records INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS sessions(
          token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created_at TEXT NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id))""")
        c.execute("""CREATE TABLE IF NOT EXISTS health_issues(
          id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER NOT NULL, issue TEXT NOT NULL,
          symptoms TEXT NOT NULL, severity TEXT NOT NULL, notes TEXT DEFAULT '', created_at TEXT NOT NULL,
          FOREIGN KEY(patient_id) REFERENCES users(id))""")
init_db()

def now(): return datetime.now(timezone.utc).isoformat()
def pw_hash(password, salt=None):
    salt=salt or secrets.token_hex(16)
    digest=hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 240000).hex()
    return f"{salt}${digest}"
def pw_ok(password, stored):
    try:
        salt,digest=stored.split("$",1)
        return hmac.compare_digest(pw_hash(password,salt).split("$",1)[1],digest)
    except Exception: return False
def token_hash(token): return hashlib.sha256(token.encode()).hexdigest()

class RegisterRequest(BaseModel):
    name: constr(min_length=2,max_length=80)
    phone: constr(min_length=8,max_length=20)
    password: constr(min_length=8,max_length=128)
    role: Literal["patient","hospital"]="patient"
    facility: str=Field(default="",max_length=120)
class LoginRequest(BaseModel):
    phone: constr(min_length=8,max_length=20)
    password: constr(min_length=8,max_length=128)
class IssueRequest(BaseModel):
    issue: constr(min_length=2,max_length=120)
    symptoms: constr(min_length=2,max_length=1000)
    severity: Literal["mild","moderate","severe"]
    notes: str=Field(default="",max_length=1000)
class ConsentRequest(BaseModel):
    share_records: bool
class ChatRequest(BaseModel):
    message: str=Field(min_length=1,max_length=2000)
    language: Literal["en","kn","hi"]="en"
class ChatResponse(BaseModel):
    answer: str
    demo: bool=False

def current_user(authorization: str|None=Header(default=None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401,"Please log in to continue.")
    token=authorization.split(" ",1)[1].strip()
    with db() as c:
        row=c.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?",(token_hash(token),)).fetchone()
    if not row: raise HTTPException(401,"Session expired. Please log in again.")
    return dict(row)
def require_role(user, role):
    if user["role"] != role: raise HTTPException(403,f"{role.title()} account required.")
def public_user(u):
    return {"id":u["id"],"name":u["name"],"phone":u["phone"],"role":u["role"],"facility":u.get("facility",""),"share_records":bool(u.get("share_records",0))}

@app.get("/")
def root(): return {"message":"ArogyaSetu AI API is running","docs":"/docs"}
@app.get("/api/health")
def health(): return {"status":"ok","service":"ArogyaSetu AI API","database":"sqlite"}

@app.get("/api/ai-status")
def ai_status():
    # Deliberately never return the key itself.
    return {"configured": bool(os.getenv("OPENAI_API_KEY", "").strip()),
            "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")}

@app.get("/api/map-status")
def map_status():
    return {"provider": "OpenStreetMap + Nominatim + Overpass",
            "note": "Map facility search requires an internet connection; community data may be incomplete."}
@app.get("/api/guide")
def guide():
    return {"items":[{"title":"Hydration basics","content":"Drink safe water regularly. Seek care if you are concerned about severe dehydration."},{"title":"Preventing infections","content":"Wash hands with soap and water, cover coughs, and handle food and drinking water safely."},{"title":"Prepare for a clinic visit","content":"Bring a list of current medicines, allergies, symptoms and when they began, and previous records if available."}],"notice":"General education only. This is not a diagnosis or treatment plan."}

@app.post("/api/auth/register")
def register(req:RegisterRequest):
    phone="".join(ch for ch in req.phone if ch.isdigit() or ch=="+")
    if len("".join(ch for ch in phone if ch.isdigit())) < 10: raise HTTPException(400,"Enter a valid phone number.")
    if req.role=="hospital" and not req.facility.strip(): raise HTTPException(400,"Enter your hospital or clinic name.")
    if req.role=="hospital" and os.getenv("ALLOW_HOSPITAL_SIGNUP","true").lower()!="true":
        raise HTTPException(403,"Hospital self-registration is disabled. Ask the system administrator.")
    try:
        with db() as c:
            cur=c.execute("INSERT INTO users(name,phone,password_hash,role,facility,share_records,created_at) VALUES(?,?,?,?,?,?,?)",
                (req.name.strip(),phone,pw_hash(req.password),req.role,req.facility.strip(),0,now()))
            uid=cur.lastrowid
    except sqlite3.IntegrityError: raise HTTPException(409,"An account with this phone number already exists. Please log in.")
    token=secrets.token_urlsafe(32)
    with db() as c: c.execute("INSERT INTO sessions(token_hash,user_id,created_at) VALUES(?,?,?)",(token_hash(token),uid,now()))
    with db() as c: u=dict(c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone())
    return {"token":token,"user":public_user(u),"message":"Account created. Phone/SMS verification is not enabled in this prototype."}

@app.post("/api/auth/login")
def login(req:LoginRequest):
    phone="".join(ch for ch in req.phone if ch.isdigit() or ch=="+")
    with db() as c: row=c.execute("SELECT * FROM users WHERE phone=?",(phone,)).fetchone()
    if not row or not pw_ok(req.password,row["password_hash"]): raise HTTPException(401,"Phone number or password is incorrect.")
    token=secrets.token_urlsafe(32)
    with db() as c: c.execute("INSERT INTO sessions(token_hash,user_id,created_at) VALUES(?,?,?)",(token_hash(token),row["id"],now()))
    return {"token":token,"user":public_user(dict(row))}
@app.get("/api/auth/me")
def me(user=Depends(current_user)): return {"user":public_user(user)}
@app.post("/api/auth/logout")
def logout(authorization: str|None=Header(default=None), user=Depends(current_user)):
    token=authorization.split(" ",1)[1].strip()
    with db() as c: c.execute("DELETE FROM sessions WHERE token_hash=?",(token_hash(token),))
    return {"ok":True}

@app.patch("/api/patient/consent")
def consent(req:ConsentRequest,user=Depends(current_user)):
    require_role(user,"patient")
    with db() as c: c.execute("UPDATE users SET share_records=? WHERE id=?",(int(req.share_records),user["id"]))
    return {"share_records":req.share_records}
@app.post("/api/patient/issues")
def add_issue(req:IssueRequest,user=Depends(current_user)):
    require_role(user,"patient")
    with db() as c:
        c.execute("INSERT INTO health_issues(patient_id,issue,symptoms,severity,notes,created_at) VALUES(?,?,?,?,?,?)",
                  (user["id"],req.issue.strip(),req.symptoms.strip(),req.severity,req.notes.strip(),now()))
    return {"ok":True,"message":"Health concern saved to your account."}
@app.get("/api/patient/issues")
def patient_issues(user=Depends(current_user)):
    require_role(user,"patient")
    with db() as c: rows=c.execute("SELECT id,issue,symptoms,severity,notes,created_at FROM health_issues WHERE patient_id=? ORDER BY id DESC",(user["id"],)).fetchall()
    return {"items":[dict(r) for r in rows],"share_records":bool(user["share_records"])}
@app.get("/api/hospital/patients")
def hospital_patients(user=Depends(current_user)):
    require_role(user,"hospital")
    with db() as c:
        rows=c.execute("""SELECT u.id AS patient_id,u.name,u.phone,i.id AS issue_id,i.issue,i.symptoms,i.severity,i.notes,i.created_at
          FROM users u JOIN health_issues i ON i.patient_id=u.id
          WHERE u.role='patient' AND u.share_records=1 ORDER BY i.created_at DESC""").fetchall()
    return {"items":[dict(r) for r in rows],"notice":"Only patient records shared with consent are shown."}

urgent_terms = ["can't breathe","cannot breathe","difficulty breathing","shortness of breath","chest pain","unconscious","heavy bleeding","seizure","stroke","ಉಸಿರಾಡಲು ಆಗುತ್ತಿಲ್ಲ","ಎದೆನೋವು","ಪ್ರಜ್ಞೆ ತಪ್ಪಿ","ಸांस नहीं","सीने में दर्द","बेहोश","भारी रक्तस्राव"]
urgent_text = {
"en":"This may be an emergency. Call local emergency services now (112 in India) or go to the nearest emergency department. Do not wait for an online response. I cannot assess your condition remotely.",
"kn":"ಇದು ತುರ್ತು ಪರಿಸ್ಥಿತಿಯಾಗಿರಬಹುದು. ತಕ್ಷಣ ಸ್ಥಳೀಯ ತುರ್ತು ಸೇವೆಗಳಿಗೆ ಕರೆ ಮಾಡಿ (ಭಾರತದಲ್ಲಿ 112) ಅಥವಾ ಹತ್ತಿರದ ತುರ್ತು ಚಿಕಿತ್ಸಾ ವಿಭಾಗಕ್ಕೆ ಹೋಗಿ. ಆನ್‌ಲೈನ್ ಉತ್ತರಕ್ಕಾಗಿ ಕಾಯಬೇಡಿ.",
"hi":"यह आपातकाल हो सकता है। तुरंत स्थानीय आपातकालीन सेवाओं को कॉल करें (भारत में 112) या निकटतम आपातकालीन विभाग जाएँ। ऑनलाइन उत्तर की प्रतीक्षा न करें।"}
def local_answer(msg,lang):
    q=msg.lower()
    answers={
      "hydration":("Drink safe water regularly. Signs of dehydration can include thirst, dark urine, dry mouth, dizziness, and reduced urination. Severe weakness, confusion, fainting, or inability to keep fluids down needs urgent medical assessment.",
                   "ಸುರಕ್ಷಿತ ನೀರನ್ನು ನಿಯಮಿತವಾಗಿ ಕುಡಿಯಿರಿ. ಬಾಯಾರಿಕೆ, ಗಾಢ ಮೂತ್ರ, ಬಾಯಿ ಒಣಗುವುದು ಮತ್ತು ತಲೆಸುತ್ತುವುದು ನೀರಿನ ಕೊರತೆಯ ಲಕ್ಷಣಗಳಾಗಿರಬಹುದು. ತೀವ್ರ ದುರ್ಬಲತೆ ಅಥವಾ ಗೊಂದಲ ಇದ್ದರೆ ತಕ್ಷಣ ವೈದ್ಯಕೀಯ ಸಹಾಯ ಪಡೆಯಿರಿ.",
                   "नियमित रूप से सुरक्षित पानी पिएँ। प्यास, गहरे रंग का पेशाब, मुँह सूखना और चक्कर आना पानी की कमी के संकेत हो सकते हैं। गंभीर कमजोरी या भ्रम हो तो तुरंत चिकित्सा सहायता लें."),
      "fever":("Rest, drink fluids, and monitor your temperature and symptoms. Seek urgent care for trouble breathing, confusion, a seizure, stiff neck, severe dehydration, or rapid worsening. A clinician can advise based on age and medical history.",
               "ವಿಶ್ರಾಂತಿ ಪಡೆಯಿರಿ, ದ್ರವಗಳನ್ನು ಕುಡಿಯಿರಿ ಮತ್ತು ತಾಪಮಾನ ಹಾಗೂ ಲಕ್ಷಣಗಳನ್ನು ಗಮನಿಸಿ. ಉಸಿರಾಟದ ತೊಂದರೆ, ಗೊಂದಲ, ಸೆಳೆತ ಅಥವಾ ತೀವ್ರ ನೀರಿನ ಕೊರತೆ ಇದ್ದರೆ ತಕ್ಷಣ ಚಿಕಿತ್ಸೆ ಪಡೆಯಿರಿ.",
               "आराम करें, तरल लें और तापमान व लक्षणों पर नज़र रखें। साँस की परेशानी, भ्रम, दौरा या गंभीर निर्जलीकरण हो तो तुरंत चिकित्सा सहायता लें."),
      "clinic":("Before your visit, note when symptoms started, current medicines, allergies, known conditions, and questions you want to ask. Bring previous reports if available. Do not delay urgent care for paperwork.",
                "ಕ್ಲಿನಿಕ್‌ಗೆ ಹೋಗುವ ಮೊದಲು ಲಕ್ಷಣಗಳು ಯಾವಾಗ ಆರಂಭವಾದವು, ಬಳಸುವ ಔಷಧಿಗಳು, ಅಲರ್ಜಿಗಳು ಮತ್ತು ಪ್ರಶ್ನೆಗಳನ್ನು ಬರೆಯಿರಿ. ಹಿಂದಿನ ವರದಿಗಳಿದ್ದರೆ ತೆಗೆದುಕೊಂಡು ಹೋಗಿ. ತುರ್ತು ಆರೈಕೆಯನ್ನು ವಿಳಂಬಿಸಬೇಡಿ.",
                "क्लिनिक जाने से पहले लक्षण कब शुरू हुए, दवाएँ, एलर्जी और अपने सवाल लिख लें। पुरानी रिपोर्ट साथ रखें। आपातकालीन देखभाल में देरी न करें."),
      "cough":("For a mild cough, rest, drink fluids, and avoid smoke. Seek medical advice if symptoms persist or worsen. Trouble breathing, chest pain, blue lips, or coughing blood needs urgent care.",
               "ಸಣ್ಣ ಕೆಮ್ಮಿಗೆ ವಿಶ್ರಾಂತಿ ಪಡೆಯಿರಿ, ದ್ರವಗಳನ್ನು ಕುಡಿಯಿರಿ ಮತ್ತು ಹೊಗೆಯನ್ನು ತಪ್ಪಿಸಿ. ಲಕ್ಷಣಗಳು ಹೆಚ್ಚಾದರೆ ವೈದ್ಯರನ್ನು ಸಂಪರ್ಕಿಸಿ. ಉಸಿರಾಟದ ತೊಂದರೆ ಅಥವಾ ಎದೆನೋವಿದ್ದರೆ ತಕ್ಷಣ ಸಹಾಯ ಪಡೆಯಿರಿ.",
               "हल्की खाँसी में आराम करें, तरल लें और धुएँ से बचें। लक्षण बढ़ें तो डॉक्टर से बात करें। साँस की परेशानी या सीने में दर्द हो तो तुरंत सहायता लें.")
    }
    if any(k in q for k in ["heart attack","heart-attack","myocardial infarction","ಹೃದಯಾಘಾತ","दिल का दौरा","हार्ट अटैक"]):
        return {
          "en":"Possible heart attack warning signs include chest pressure, tightness or pain; pain spreading to an arm, back, neck or jaw; shortness of breath; cold sweat; nausea; or sudden light-headedness. Symptoms can vary and may be subtle. If you or someone else may be having these symptoms now, call 112 in India immediately and do not drive yourself. This information cannot diagnose a heart attack.",
          "kn":"ಹೃದಯಾಘಾತದ ಎಚ್ಚರಿಕೆ ಲಕ್ಷಣಗಳಲ್ಲಿ ಎದೆಯಲ್ಲಿ ಒತ್ತಡ/ನೋವು, ಕೈ/ಬೆನ್ನು/ಕುತ್ತಿಗೆ/ದವಡೆಗೆ ಹರಡುವ ನೋವು, ಉಸಿರಾಟದ ತೊಂದರೆ, ತಣ್ಣನೆಯ ಬೆವರು, ವಾಕರಿಕೆ ಅಥವಾ ತಲೆಸುತ್ತು ಸೇರಿರಬಹುದು. ಲಕ್ಷಣಗಳು ಈಗ ಇದ್ದರೆ ಭಾರತದಲ್ಲಿ ತಕ್ಷಣ 112ಕ್ಕೆ ಕರೆ ಮಾಡಿ; ಸ್ವತಃ ವಾಹನ ಚಲಾಯಿಸಬೇಡಿ. ಈ ಮಾಹಿತಿ ರೋಗನಿರ್ಣಯವಲ್ಲ.",
          "hi":"दिल के दौरे के चेतावनी संकेतों में सीने में दबाव या दर्द, बाँह/पीठ/गर्दन/जबड़े तक फैलता दर्द, साँस फूलना, ठंडा पसीना, मतली या अचानक चक्कर शामिल हो सकते हैं। यदि अभी ऐसे लक्षण हैं, तो भारत में तुरंत 112 पर कॉल करें और स्वयं गाड़ी न चलाएँ। यह निदान नहीं है।"
        }[lang]
    if any(k in q for k in ["dehydrat","water","thirst","ನೀರಿನ ಕೊರತೆ","पानी की कमी"]): key="hydration"
    elif any(k in q for k in ["fever","temperature","ಜ್ವರ","बुखार"]): key="fever"
    elif any(k in q for k in ["clinic","doctor","hospital","appointment","ಆಸ್ಪತ್ರೆ","ವೈದ್ಯ","डॉक्टर","अस्पताल"]): key="clinic"
    elif any(k in q for k in ["cough","cold","ಕೆಮ್ಮು","खाँसी","खांसी"]): key="cough"
    else: key=None
    if key: return answers[key][{"en":0,"kn":1,"hi":2}[lang]]
    fallback={"en":"I can help with general health education. Tell me the main symptom and how long it has been happening, without sharing your name or other identifying details. I cannot diagnose or prescribe medicine. If symptoms are severe or worsening, seek medical care.",
              "kn":"ನಾನು ಸಾಮಾನ್ಯ ಆರೋಗ್ಯ ಮಾಹಿತಿಯನ್ನು ನೀಡಬಹುದು. ನಿಮ್ಮ ಹೆಸರನ್ನು ಹಂಚಿಕೊಳ್ಳದೆ ಮುಖ್ಯ ಲಕ್ಷಣ ಮತ್ತು ಅದು ಎಷ್ಟು ಸಮಯದಿಂದ ಇದೆ ಎಂದು ತಿಳಿಸಿ. ನಾನು ರೋಗನಿರ್ಣಯ ಅಥವಾ ಔಷಧಿ ಸೂಚಿಸಲು ಸಾಧ್ಯವಿಲ್ಲ. ತೀವ್ರ ಅಥವಾ ಹೆಚ್ಚುತ್ತಿರುವ ಲಕ್ಷಣಗಳಿಗೆ ವೈದ್ಯಕೀಯ ಸಹಾಯ ಪಡೆಯಿರಿ.",
              "hi":"मैं सामान्य स्वास्थ्य जानकारी दे सकता हूँ। अपना नाम बताए बिना मुख्य लक्षण और यह कब से है बताएं। मैं निदान या दवा नहीं लिख सकता। गंभीर या बढ़ते लक्षणों पर चिकित्सा सहायता लें।"}
    return fallback[lang]
system_prompt=("You are ArogyaSetu AI, a cautious public-health information assistant. Provide general education only; never diagnose, prescribe, or recommend changing medication. For urgent symptoms advise immediate emergency care. Be concise and answer in the requested language. Do not request identifying data.")

@app.post("/api/chat",response_model=ChatResponse)
async def chat(req:ChatRequest):
    msg=req.message.strip()
    if any(term in msg.lower() for term in urgent_terms): return ChatResponse(answer=urgent_text[req.language])
    key=os.getenv("OPENAI_API_KEY","").strip()
    if not key:
        return ChatResponse(answer=local_answer(msg,req.language),demo=True)
    base=os.getenv("OPENAI_BASE_URL","https://api.openai.com/v1").rstrip("/")
    model=os.getenv("OPENAI_MODEL","gpt-4o-mini")
    language={"en":"English","kn":"Kannada","hi":"Hindi"}[req.language]
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
            r=await client.post(base+"/chat/completions",
                headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"},
                json={"model":model,"temperature":0.2,"messages":[
                    {"role":"system","content":system_prompt+f" Respond in {language}."},
                    {"role":"user","content":msg}]})
            if r.is_error:
                # Log details locally for debugging; never expose secrets to the browser.
                print(f"AI provider error: HTTP {r.status_code}: {r.text[:700]}")
                r.raise_for_status()
            payload=r.json()
            answer=(payload.get("choices") or [{}])[0].get("message",{}).get("content","").strip()
            if not answer:
                print("AI provider returned an empty response.")
                return ChatResponse(answer=local_answer(msg,req.language)+" The AI provider returned an empty response; this is basic guidance.",demo=True)
            return ChatResponse(answer=answer,demo=False)
    except httpx.TimeoutException:
        print("AI provider request timed out.")
        return ChatResponse(answer=local_answer(msg,req.language)+" The AI provider timed out. Check your connection, API quota, and provider status, then retry.",demo=True)
    except Exception as exc:
        print(f"AI provider request failed: {type(exc).__name__}: {str(exc)[:500]}")
        return ChatResponse(answer=local_answer(msg,req.language)+" The AI service request failed. Check the backend terminal for the provider error and verify the key, model, billing, and network settings.",demo=True)
