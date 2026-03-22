from dotenv import load_dotenv
load_dotenv()

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
