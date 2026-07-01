from dotenv import load_dotenv
load_dotenv()

# Kannada-script names for Karnataka districts.
# Used to build regional-language RSS queries for Kannada outlets.
KANNADA_DISTRICTS = {
    "Bengaluru":  "ಬೆಂಗಳೂರು",
    "Mysuru":     "ಮೈಸೂರು",
    "Mangaluru":  "ಮಂಗಳೂರು",
    "Hubballi":   "ಹುಬ್ಬಳ್ಳಿ",
    "Belagavi":   "ಬೆಳಗಾವಿ",
    "Dharwad":    "ಧಾರವಾಡ",
    "Kalaburagi": "ಕಲಬುರಗಿ",
    "Shivamogga": "ಶಿವಮೊಗ್ಗ",
    "Tumakuru":   "ತುಮಕೂರು",
    "Vijayapura": "ವಿಜಯಪುರ",
    "Ballari":    "ಬಳ್ಳಾರಿ",
    "Davangere":  "ದಾವಣಗೆರೆ",
    "Bidar":      "ಬೀದರ",
    "Udupi":      "ಉಡುಪಿ",
    "Raichur":    "ರಾಯಚೂರು",
    "Hassan":     "ಹಾಸನ",
}

# Regional-language query templates per state.
# {district} is replaced at runtime with the appropriate district name
# (Kannada script for Karnataka; English for all other states).
# Each list should contain exactly 2 query strings.
STATE_REGIONAL_QUERIES = {
    "Karnataka": [
        "{district} ರಾಜಕೀಯ when:2d",
        "ಕರ್ನಾಟಕ ಬಿಜೆಪಿ ಕಾಂಗ್ರೆಸ್ when:2d",
    ],
    "Tamil Nadu": [
        "{district} அரசியல் when:2d",
        "தமிழ்நாடு பாஜக காங்கிரஸ் when:2d",
    ],
    "Maharashtra": [
        "{district} राजकारण when:2d",
        "महाराष्ट्र भाजप काँग्रेस when:2d",
    ],
    "Uttar Pradesh": [
        "{district} राजनीति when:2d",
        "उत्तर प्रदेश भाजपा कांग्रेस when:2d",
    ],
    "Bihar": [
        "{district} राजनीति when:2d",
        "बिहार भाजपा जदयू when:2d",
    ],
    "Madhya Pradesh": [
        "{district} राजनीति when:2d",
        "मध्य प्रदेश भाजपा कांग्रेस when:2d",
    ],
    "Rajasthan": [
        "{district} राजनीति when:2d",
        "राजस्थान भाजपा कांग्रेस when:2d",
    ],
    "Haryana": [
        "{district} राजनीति when:2d",
        "हरियाणा भाजपा कांग्रेस when:2d",
    ],
    "Delhi": [
        "{district} राजनीति when:2d",
        "दिल्ली आप भाजपा कांग्रेस when:2d",
    ],
    "Gujarat": [
        "{district} રાજકારણ when:2d",
        "ગુજરાત ભાજપ કોંગ્રેસ when:2d",
    ],
    "West Bengal": [
        "{district} রাজনীতি when:2d",
        "পশ্চিমবঙ্গ তৃণমূল ভাজপা when:2d",
    ],
    "Andhra Pradesh": [
        "{district} రాజకీయాలు when:2d",
        "ఆంధ్రప్రదేశ్ బీజేపీ కాంగ్రెస్ when:2d",
    ],
    "Telangana": [
        "{district} రాజకీయాలు when:2d",
        "తెలంగాణ బీఆర్ఎస్ కాంగ్రెస్ when:2d",
    ],
    "Kerala": [
        "{district} രാഷ്ട്രീയം when:2d",
        "കേരളം ബിജെപി കോൺഗ്രസ് when:2d",
    ],
    "Odisha": [
        "{district} ରାଜନୀତି when:2d",
        "ଓଡ଼ିଶା ଭାଜପା କଂଗ୍ରେସ when:2d",
    ],
    "Punjab": [
        "{district} ਸਿਆਸਤ when:2d",
        "ਪੰਜਾਬ ਆਪ ਭਾਜਪਾ ਕਾਂਗਰਸ when:2d",
    ],
    "Jharkhand": [
        "{district} राजनीति when:2d",
        "झारखंड भाजपा कांग्रेस when:2d",
    ],
    "Chhattisgarh": [
        "{district} राजनीति when:2d",
        "छत्तीसगढ़ भाजपा कांग्रेस when:2d",
    ],
    "Uttarakhand": [
        "{district} राजनीति when:2d",
        "उत्तराखंड भाजपा कांग्रेस when:2d",
    ],
    "Himachal Pradesh": [
        "{district} राजनीति when:2d",
        "हिमाचल प्रदेश भाजपा कांग्रेस when:2d",
    ],
}

REGIONS = {
    "Andhra Pradesh": [
        "Visakhapatnam", "Vijayawada", "Guntur", "Nellore", "Kurnool",
        "Rajahmundry", "Tirupati", "Kakinada", "Kadapa", "Anantapur",
        "Vizianagaram", "Eluru", "Ongole", "Nandyal", "Chittoor"
    ],
    "Arunachal Pradesh": [
        "Itanagar", "Naharlagun", "Pasighat", "Tawang", "Ziro",
        "Bomdila", "Tezu", "Aalo", "Roing", "Namsai",
        "Changlang", "Seppa", "Daporijo", "Longding", "Khonsa"
    ],
    "Assam": [
        "Guwahati", "Silchar", "Dibrugarh", "Jorhat", "Nagaon",
        "Tinsukia", "Tezpur", "Bongaigaon", "Dhubri", "Lakhimpur",
        "Karimganj", "Sivasagar", "Goalpara", "Barpeta", "Golaghat"
    ],
    "Bihar": [
        "Patna", "Gaya", "Bhagalpur", "Muzaffarpur", "Purnia",
        "Darbhanga", "Ara", "Bihar Sharif", "Begusarai", "Katihar",
        "Munger", "Chhapra", "Samastipur", "Hajipur", "Sitamarhi"
    ],
    "Chhattisgarh": [
        "Raipur", "Bhilai", "Bilaspur", "Korba", "Durg",
        "Rajnandgaon", "Jagdalpur", "Raigarh", "Ambikapur", "Dhamtari",
        "Mahasamund", "Kanker", "Kondagaon", "Bastar", "Surajpur"
    ],
    "Goa": [
        "Panaji", "Margao", "Vasco da Gama", "Mapusa", "Ponda",
        "Bicholim", "Curchorem", "Sanquelim", "Canacona", "Quepem",
        "Valpoi", "Calangute", "Pernem", "Sanguem", "Mormugao"
    ],
    "Gujarat": [
        "Ahmedabad", "Surat", "Vadodara", "Rajkot", "Bhavnagar",
        "Jamnagar", "Junagadh", "Gandhinagar", "Anand", "Navsari",
        "Morbi", "Mehsana", "Surendranagar", "Bharuch", "Amreli"
    ],
    "Haryana": [
        "Faridabad", "Gurugram", "Panipat", "Ambala", "Yamunanagar",
        "Rohtak", "Hisar", "Karnal", "Sonipat", "Panchkula",
        "Bhiwani", "Sirsa", "Bahadurgarh", "Jind", "Thanesar"
    ],
    "Himachal Pradesh": [
        "Shimla", "Mandi", "Solan", "Dharamshala", "Kullu",
        "Baddi", "Palampur", "Nahan", "Sundarnagar", "Chamba",
        "Una", "Bilaspur", "Hamirpur", "Kangra", "Keylong"
    ],
    "Jharkhand": [
        "Ranchi", "Jamshedpur", "Dhanbad", "Bokaro", "Deoghar",
        "Phusro", "Hazaribagh", "Giridih", "Ramgarh", "Medininagar",
        "Chirkunda", "Chaibasa", "Dumka", "Gumla", "Simdega"
    ],
    "Karnataka": [
        "Bengaluru", "Mysuru", "Hubballi", "Mangaluru", "Belagavi",
        "Kalaburagi", "Ballari", "Vijayapura", "Shivamogga", "Tumkuru",
        "Davangere", "Bidar", "Udupi", "Raichur", "Hassan"
    ],
    "Kerala": [
        "Thiruvananthapuram", "Kochi", "Kozhikode", "Thrissur", "Kollam",
        "Palakkad", "Alappuzha", "Malappuram", "Kannur", "Kasaragod",
        "Kottayam", "Idukki", "Ernakulam", "Wayanad", "Pathanamthitta"
    ],
    "Madhya Pradesh": [
        "Bhopal", "Indore", "Jabalpur", "Gwalior", "Ujjain",
        "Sagar", "Rewa", "Satna", "Dewas", "Chhindwara",
        "Ratlam", "Burhanpur", "Singrauli", "Katni", "Morena"
    ],
    "Maharashtra": [
        "Mumbai", "Pune", "Nagpur", "Nashik", "Aurangabad",
        "Solapur", "Thane", "Kolhapur", "Amravati", "Nanded",
        "Sangli", "Malegaon", "Jalgaon", "Akola", "Latur"
    ],
    "Manipur": [
        "Imphal", "Thoubal", "Bishnupur", "Churachandpur", "Senapati",
        "Ukhrul", "Chandel", "Tamenglong", "Jiribam", "Kakching",
        "Noney", "Pherzawl", "Kangpokpi", "Kamjong", "Tengnoupal"
    ],
    "Meghalaya": [
        "Shillong", "Tura", "Jowai", "Nongstoin", "Baghmara",
        "Williamnagar", "Resubelpara", "Ampati", "Mawkyrwat", "Nongpoh",
        "Cherrapunjee", "Mairang", "Khliehriat", "Sohra", "Mawlai"
    ],
    "Mizoram": [
        "Aizawl", "Lunglei", "Saiha", "Champhai", "Kolasib",
        "Serchhip", "Lawngtlai", "Mamit", "Siaha", "Khawzawl",
        "Hnahthial", "Saitual", "Thenzawl", "Tlabung", "Bairabi"
    ],
    "Nagaland": [
        "Kohima", "Dimapur", "Mokokchung", "Tuensang", "Wokha",
        "Zunheboto", "Phek", "Mon", "Kiphire", "Longleng",
        "Peren", "Noklak", "Tseminyu", "Meluri", "Chumoukedima"
    ],
    "Odisha": [
        "Bhubaneswar", "Cuttack", "Rourkela", "Brahmapur", "Sambalpur",
        "Puri", "Balasore", "Bhadrak", "Baripada", "Jharsuguda",
        "Jeypore", "Bargarh", "Kendujhar", "Koraput", "Rayagada"
    ],
    "Punjab": [
        "Ludhiana", "Amritsar", "Jalandhar", "Patiala", "Bathinda",
        "Mohali", "Firozpur", "Hoshiarpur", "Gurdaspur", "Sangrur",
        "Pathankot", "Moga", "Abohar", "Faridkot", "Muktsar"
    ],
    "Rajasthan": [
        "Jaipur", "Jodhpur", "Kota", "Bikaner", "Ajmer",
        "Udaipur", "Bhilwara", "Alwar", "Bharatpur", "Sikar",
        "Pali", "Barmer", "Ganganagar", "Tonk", "Churu"
    ],
    "Sikkim": [
        "Gangtok", "Namchi", "Gyalshing", "Mangan", "Rangpo",
        "Singtam", "Jorethang", "Nayabazar", "Ravangla", "Soreng",
        "Pakyong", "Rongli", "Chungthang", "Lachen", "Lachung"
    ],
    "Tamil Nadu": [
        "Chennai", "Coimbatore", "Madurai", "Tiruchirappalli", "Salem",
        "Tirunelveli", "Vellore", "Erode", "Thoothukudi", "Dindigul",
        "Thanjavur", "Ranipet", "Sivakasi", "Karur", "Hosur"
    ],
    "Telangana": [
        "Hyderabad", "Warangal", "Nizamabad", "Karimnagar", "Ramagundam",
        "Khammam", "Mahbubnagar", "Nalgonda", "Adilabad", "Suryapet",
        "Miryalaguda", "Siddipet", "Mancherial", "Jagtial", "Kothagudem"
    ],
    "Tripura": [
        "Agartala", "Dharmanagar", "Udaipur", "Kailashahar", "Belonia",
        "Khowai", "Ambassa", "Sabroom", "Sonamura", "Bishalgarh",
        "Amarpur", "Kamalpur", "Melaghar", "Teliamura", "Jogendranagar"
    ],
    "Uttar Pradesh": [
        "Lucknow", "Kanpur", "Agra", "Varanasi", "Prayagraj",
        "Meerut", "Ghaziabad", "Noida", "Bareilly", "Aligarh",
        "Moradabad", "Gorakhpur", "Saharanpur", "Firozabad", "Mathura"
    ],
    "Uttarakhand": [
        "Dehradun", "Haridwar", "Roorkee", "Haldwani", "Rudrapur",
        "Kashipur", "Rishikesh", "Pithoragarh", "Tehri", "Pauri",
        "Almora", "Nainital", "Champawat", "Uttarkashi", "Bageshwar"
    ],
    "West Bengal": [
        "Kolkata", "Asansol", "Siliguri", "Durgapur", "Bardhaman",
        "Malda", "Barasat", "Krishnanagar", "Midnapore", "Howrah",
        "Jalpaiguri", "Cooch Behar", "Purulia", "Bankura", "Murshidabad"
    ],
    "Delhi": [
        "New Delhi", "Dwarka", "Rohini", "Janakpuri", "Saket",
        "Lajpat Nagar", "Karol Bagh", "Shahdara", "Pitampura", "Mayur Vihar",
        "Vasant Kunj", "Nehru Place", "Connaught Place", "Chandni Chowk", "Narela"
    ],
    "Jammu & Kashmir": [
        "Srinagar", "Jammu", "Anantnag", "Baramulla", "Sopore",
        "Udhampur", "Kathua", "Rajouri", "Poonch", "Doda",
        "Kupwara", "Pulwama", "Shopian", "Kulgam", "Ganderbal"
    ],
    "Ladakh": [
        "Leh", "Kargil", "Diskit", "Padum", "Zanskar",
        "Drass", "Nubra", "Khalsi", "Sankoo", "Turtuk",
        "Nyoma", "Chushul", "Hanle", "Tangtse", "Durbuk"
    ],
    "Puducherry": [
        "Puducherry", "Karaikal", "Mahe", "Yanam", "Villianur",
        "Ozhukarai", "Ariyankuppam", "Mannadipet", "Bahour", "Nettapakkam",
        "Thirubuvanai", "Kirumampakkam", "Kadirkamam", "Muthialpet", "Orleanpet"
    ],
}
