# Outlet definitions for PolitiScan
# STATE_OUTLETS: state name -> list of major outlets (English + regional language)
# OUTLET_DOMAINS: outlet display name -> primary domain for NewsData.io domainurl filter

STATE_OUTLETS = {
    "Andhra Pradesh": [
        "The Hindu", "NDTV", "Deccan Chronicle", "Hans India",
        "Andhra Jyothi", "Eenadu", "Sakshi", "TV9 Telugu", "ABN Andhra Jyothi",
    ],
    "Arunachal Pradesh": [
        "NDTV", "The Hindu", "Arunachal Times", "Arunachal Front",
        "The Sentinel", "Northeast Now", "EastMojo", "Morung Express",
    ],
    "Assam": [
        "The Hindu", "NDTV", "The Sentinel", "Assam Tribune",
        "Northeast Now", "EastMojo", "Pratidin Time", "News Live Assam", "G Plus",
    ],
    "Bihar": [
        "NDTV", "Hindustan Times", "Times of India", "Hindustan",
        "Dainik Jagran", "Dainik Bhaskar", "Prabhat Khabar", "News18",
    ],
    "Chhattisgarh": [
        "NDTV", "Times of India", "Dainik Jagran", "Dainik Bhaskar",
        "Nai Dunia", "Haribhoomi", "IBC24", "ETV Bharat",
    ],
    "Goa": [
        "NDTV", "Times of India", "Herald Goa", "Navhind Times",
        "Gomantak", "Prudent Media", "Goa365", "O Heraldo",
    ],
    "Gujarat": [
        "NDTV", "Times of India", "Indian Express", "Divya Bhaskar",
        "Gujarat Samachar", "Sandesh", "TV9 Gujarati", "Zee 24 Kalak",
    ],
    "Haryana": [
        "NDTV", "Hindustan Times", "Times of India", "Dainik Jagran",
        "Dainik Bhaskar", "Punjab Kesari", "Amar Ujala", "Tribune India",
    ],
    "Himachal Pradesh": [
        "NDTV", "Hindustan Times", "Tribune India", "Dainik Jagran",
        "Dainik Bhaskar", "Divya Himachal", "Amar Ujala", "ETV Bharat",
    ],
    "Jharkhand": [
        "NDTV", "Times of India", "Hindustan Times", "Dainik Jagran",
        "Dainik Bhaskar", "Prabhat Khabar", "News18", "ETV Bharat",
    ],
    "Karnataka": [
        "The Hindu", "Deccan Herald", "Indian Express", "NDTV",
        "Vijaya Karnataka", "Prajavani", "Udayavani", "TV9 Kannada", "Kannada Prabha",
    ],
    "Kerala": [
        "The Hindu", "Indian Express", "NDTV", "Mathrubhumi",
        "Malayala Manorama", "Asianet News", "MediaOne", "Manorama News", "Reporter Live",
    ],
    "Madhya Pradesh": [
        "NDTV", "Times of India", "Dainik Jagran", "Dainik Bhaskar",
        "Nai Dunia", "Patrika", "Nava Dunia", "ETV Bharat",
    ],
    "Maharashtra": [
        "Indian Express", "Times of India", "NDTV", "Hindustan Times",
        "Loksatta", "Maharashtra Times", "Lokmat", "Zee 24 Taas", "ABP Majha",
    ],
    "Manipur": [
        "NDTV", "The Hindu", "Sangai Express", "Imphal Free Press",
        "Morung Express", "EastMojo", "Northeast Now", "E-Pao",
    ],
    "Meghalaya": [
        "NDTV", "The Hindu", "Shillong Times", "Meghalaya Guardian",
        "Northeast Now", "EastMojo", "Morung Express", "Northeast Today",
    ],
    "Mizoram": [
        "NDTV", "The Hindu", "Vanglaini", "Aizawl Post",
        "EastMojo", "Northeast Now", "Morung Express", "Millennium Post",
    ],
    "Nagaland": [
        "NDTV", "The Hindu", "Nagaland Post", "Morung Express",
        "EastMojo", "Northeast Now", "Eastern Mirror", "The Sentinel",
    ],
    "Odisha": [
        "The Hindu", "NDTV", "Times of India", "Sambad",
        "Dharitri", "Pragativadi", "OTV", "Odisha TV", "Kanak News",
    ],
    "Punjab": [
        "NDTV", "Hindustan Times", "Tribune India", "Times of India",
        "Dainik Jagran", "Punjab Kesari", "Dainik Bhaskar", "Jagbani",
    ],
    "Rajasthan": [
        "NDTV", "Times of India", "Dainik Jagran", "Dainik Bhaskar",
        "Rajasthan Patrika", "Navbharat Times", "Amar Ujala", "ETV Bharat",
    ],
    "Sikkim": [
        "NDTV", "The Hindu", "Sikkim Express", "EastMojo",
        "Northeast Now", "The Statesman", "Northeast Today", "Himalayan Mewsline",
    ],
    "Tamil Nadu": [
        "The Hindu", "Indian Express", "NDTV", "Dinamalar",
        "Dinamani", "Daily Thanthi", "Puthiya Thalaimurai", "Sun News", "Polimer News",
    ],
    "Telangana": [
        "The Hindu", "NDTV", "Deccan Chronicle", "Hans India",
        "Eenadu", "Sakshi", "TV9 Telugu", "V6 News", "Telangana Today",
    ],
    "Tripura": [
        "NDTV", "The Hindu", "Dainik Sambad", "Tripura Tribune",
        "Northeast Now", "EastMojo", "The Sentinel", "Agartala Today",
    ],
    "Uttar Pradesh": [
        "NDTV", "Hindustan Times", "Times of India", "Dainik Jagran",
        "Dainik Bhaskar", "Amar Ujala", "Navbharat Times", "News18",
    ],
    "Uttarakhand": [
        "NDTV", "Hindustan Times", "Times of India", "Dainik Jagran",
        "Dainik Bhaskar", "Amar Ujala", "Tribune India", "ETV Bharat",
    ],
    "West Bengal": [
        "The Hindu", "Times of India", "Hindustan Times", "NDTV",
        "Anandabazar Patrika", "Aajkaal", "Sangbad Pratidin", "ABP Ananda", "Zee 24 Ghanta",
    ],
    "Delhi": [
        "Hindustan Times", "Times of India", "Indian Express", "NDTV",
        "The Hindu", "Navbharat Times", "Dainik Jagran", "Amar Ujala", "India TV",
    ],
    "Jammu & Kashmir": [
        "NDTV", "Times of India", "Greater Kashmir", "Kashmir Observer",
        "Daily Excelsior", "Kashmir Times", "Rising Kashmir", "State Times",
    ],
    "Ladakh": [
        "NDTV", "The Hindu", "Daily Excelsior", "Kashmir Times",
        "Greater Kashmir", "Reach Ladakh", "State Times", "ETV Bharat",
    ],
    "Puducherry": [
        "The Hindu", "NDTV", "Indian Express", "Dinamalar",
        "Dinamani", "Daily Thanthi", "Puducherry Today", "Tamil Murasu",
    ],
}

OUTLET_DOMAINS = {
    # National English
    "The Hindu":          "thehindu.com",
    "NDTV":               "ndtv.com",
    "Indian Express":     "indianexpress.com",
    "Hindustan Times":    "hindustantimes.com",
    "Times of India":     "timesofindia.com",
    "Business Standard":  "business-standard.com",
    "Deccan Chronicle":   "deccanchronicle.com",
    "Deccan Herald":      "deccanherald.com",
    "The Wire":           "thewire.in",
    "Scroll":             "scroll.in",
    "Republic TV":        "republicworld.com",
    "India Today":        "indiatoday.in",
    "Tribune India":      "tribuneindia.com",
    "The Statesman":      "thestatesman.com",
    "Hans India":         "thehansindia.com",
    "Free Press Journal": "freepressjournal.in",
    "Millennium Post":    "millenniumpost.in",
    "India TV":           "indiatvnews.com",
    "News18":             "news18.com",
    "ETV Bharat":         "etvbharat.com",
    # Telugu
    "Andhra Jyothi":      "andhrajyothy.com",
    "Eenadu":             "eenadu.net",
    "Sakshi":             "sakshi.com",
    "TV9 Telugu":         "tv9telugu.com",
    "ABN Andhra Jyothi":  "abnnews.in",
    "Telangana Today":    "telanganatoday.com",
    "V6 News":            "v6news.tv",
    # Northeast
    "Arunachal Times":    "arunachaltimes.in",
    "Arunachal Front":    "arunachalfront.com",
    "The Sentinel":       "sentinelassam.com",
    "Northeast Now":      "nenow.in",
    "EastMojo":           "eastmojo.com",
    "Assam Tribune":      "assamtribune.com",
    "Northeast Today":    "northeasttoday.in",
    "Imphal Free Press":  "ifp.co.in",
    "Morung Express":     "morungexpress.com",
    "Nagaland Post":      "nagalandpost.com",
    "Eastern Mirror":     "easternmirrornagaland.com",
    "Shillong Times":     "theshillongtimes.com",
    "Meghalaya Guardian": "meghalayaguardian.com",
    "Vanglaini":          "vanglaini.org",
    "Dainik Sambad":      "dainiktripurabarta.com",
    "Tripura Tribune":    "tripuratribune.com",
    "Agartala Today":     "agartalatoday.com",
    "Sikkim Express":     "sikkimexpress.com",
    "G Plus":             "guwahatiplus.com",
    "Pratidin Time":      "pratidintime.com",
    "News Live Assam":    "newslive.in",
    "Himalayan Mewsline": "himalayanmewsline.com",
    "E-Pao":              "e-pao.net",
    "Sangai Express":     "e-pao.net",
    "Aizawl Post":        "aizawlpost.com",
    # Hindi belt
    "Dainik Jagran":      "jagran.com",
    "Dainik Bhaskar":     "bhaskar.com",
    "Amar Ujala":         "amarujala.com",
    "Navbharat Times":    "navbharattimes.indiatimes.com",
    "Punjab Kesari":      "punjabkesari.in",
    "Prabhat Khabar":     "prabhatkhabar.com",
    "Nai Dunia":          "naidunia.com",
    "Nava Dunia":         "navadunia.com",
    "Haribhoomi":         "haribhoomi.com",
    "Rajasthan Patrika":  "patrika.com",
    "Divya Himachal":     "divyahimachal.com",
    "Hindustan":          "livehindustan.com",
    "IBC24":              "ibc24.in",
    # Kannada
    "Vijaya Karnataka":   "vijaykarnataka.com",
    "Prajavani":          "prajavani.net",
    "Udayavani":          "udayavani.com",
    "TV9 Kannada":        "tv9kannada.com",
    "Kannada Prabha":     "kannadaprabha.com",
    # Malayalam
    "Mathrubhumi":        "mathrubhumi.com",
    "Malayala Manorama":  "manoramaonline.com",
    "Asianet News":       "asianetnews.com",
    "MediaOne":           "mediaoneindia.com",
    "Manorama News":      "manoramaonline.com",
    "Reporter Live":      "reporterlive.com",
    # Gujarati
    "Divya Bhaskar":      "divyabhaskar.co.in",
    "Gujarat Samachar":   "gujaratsamachar.com",
    "Sandesh":            "sandesh.com",
    "TV9 Gujarati":       "tv9gujarati.com",
    "Zee 24 Kalak":       "zee24kalak.com",
    # Marathi
    "Loksatta":           "loksatta.com",
    "Maharashtra Times":  "maharashtratimes.indiatimes.com",
    "Lokmat":             "lokmat.com",
    "Zee 24 Taas":        "zeenews.india.com",
    "ABP Majha":          "abpmajha.abplive.com",
    # Tamil
    "Dinamalar":          "dinamalar.com",
    "Dinamani":           "dinamani.com",
    "Daily Thanthi":      "dailythanthi.com",
    "Puthiya Thalaimurai":"puthiyathalaimurai.tv",
    "Sun News":           "sunnewsonline.com",
    "Polimer News":       "polimernews.com",
    "Tamil Murasu":       "tamilmurasu.com.sg",
    # Odia
    "Sambad":             "sambad.com",
    "Dharitri":           "dharitri.com",
    "Pragativadi":        "pragativadi.com",
    "OTV":                "odishatv.in",
    "Odisha TV":          "odishatv.in",
    "Kanak News":         "kanakodisha.com",
    # Punjabi
    "Jagbani":            "jagbani.punjabkesari.in",
    # Goa
    "Herald Goa":         "heraldgoa.in",
    "Navhind Times":      "navhindtimes.in",
    "Gomantak":           "gomantak.com",
    "Prudent Media":      "prudentmedia.in",
    "Goa365":             "goa365tv.com",
    "O Heraldo":          "heraldo.in",
    # J&K
    "Greater Kashmir":    "greaterkashmir.com",
    "Kashmir Observer":   "kashmirobserver.net",
    "Daily Excelsior":    "dailyexcelsior.com",
    "Kashmir Times":      "kashmirtimes.com",
    "Rising Kashmir":     "risingkashmir.com",
    "State Times":        "statetimes.in",
    "Reach Ladakh":       "reachladakh.com",
    # West Bengal
    "ABP Ananda":         "abpananda.abplive.com",
    "Zee 24 Ghanta":      "zee24ghanta.com",
    "Anandabazar Patrika":"anandabazar.com",
    "Aajkaal":            "aajkaal.in",
    "Sangbad Pratidin":   "sangbadpratidin.in",
}
