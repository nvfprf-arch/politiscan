# Language configuration for PolitiScan

# ISO 639-1 code -> display name (covers langdetect output codes)
LANGUAGE_CODES = {
    "kn": "Kannada",
    "te": "Telugu",
    "ta": "Tamil",
    "ml": "Malayalam",
    "mr": "Marathi",
    "hi": "Hindi",
    "bn": "Bengali",
    "gu": "Gujarati",
    "pa": "Punjabi",
    "en": "English",
    "or": "Odia",
    "as": "Assamese",
    "ur": "Urdu",
}

# State -> primary regional language (used as fallback when detection is uncertain)
STATE_PRIMARY_LANGUAGE = {
    "Andhra Pradesh":    "Telugu",
    "Arunachal Pradesh": "English",
    "Assam":             "Bengali",
    "Bihar":             "Hindi",
    "Chhattisgarh":      "Hindi",
    "Goa":               "English",
    "Gujarat":           "Gujarati",
    "Haryana":           "Hindi",
    "Himachal Pradesh":  "Hindi",
    "Jharkhand":         "Hindi",
    "Karnataka":         "Kannada",
    "Kerala":            "Malayalam",
    "Madhya Pradesh":    "Hindi",
    "Maharashtra":       "Marathi",
    "Manipur":           "English",
    "Meghalaya":         "English",
    "Mizoram":           "English",
    "Nagaland":          "English",
    "Odisha":            "Odia",
    "Punjab":            "Punjabi",
    "Rajasthan":         "Hindi",
    "Sikkim":            "English",
    "Tamil Nadu":        "Tamil",
    "Telangana":         "Telugu",
    "Tripura":           "Bengali",
    "Uttar Pradesh":     "Hindi",
    "Uttarakhand":       "Hindi",
    "West Bengal":       "Bengali",
    "Delhi":             "Hindi",
    "Jammu & Kashmir":   "Hindi",
    "Ladakh":            "Hindi",
    "Puducherry":        "Tamil",
}

# Language display name -> Tesseract 3-letter OCR code
TESSERACT_CODES = {
    "Kannada":   "kan",
    "Telugu":    "tel",
    "Tamil":     "tam",
    "Malayalam": "mal",
    "Marathi":   "mar",
    "Hindi":     "hin",
    "Bengali":   "ben",
}
