"""Restaurants offered in the button flow: name -> areas. Sample data, edit to taste.
WhatsApp lists allow at most 10 rows, so keep this to 10 restaurants or fewer."""
RESTAURANTS: dict[str, list[str]] = {
    "Saravana Bhavan": ["Anna Nagar", "T Nagar"],
    "Murugan Idli Shop": ["Besant Nagar"],
    "Dindigul Thalappakatti": ["Adyar", "Velachery"],
}

# Phone numbers Halo may call, in +country-code form. Calls only go to numbers listed here.
PHONES: dict[str, str] = {}
