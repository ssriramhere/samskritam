"""Learner-facing labels for grammatical features: Sanskrit term + English."""

CASE = {"Nom": ("prathamā", "nominative"), "Acc": ("dvitīyā", "accusative"),
        "Ins": ("tṛtīyā", "instrumental"), "Dat": ("caturthī", "dative"),
        "Abl": ("pañcamī", "ablative"), "Gen": ("ṣaṣṭhī", "genitive"),
        "Loc": ("saptamī", "locative"), "Voc": ("sambodhana", "vocative"),
        "Cpd": ("samāsa-pūrvapada", "compound member")}
NUMBER = {"Sing": ("ekavacana", "singular"), "Dual": ("dvivacana", "dual"),
          "Plur": ("bahuvacana", "plural")}
GENDER = {"Masc": ("puṃliṅga", "masculine"), "Fem": ("strīliṅga", "feminine"),
          "Neut": ("napuṃsakaliṅga", "neuter")}
PERSON = {"3": ("prathama-puruṣa", "3rd person"),
          "2": ("madhyama-puruṣa", "2nd person"),
          "1": ("uttama-puruṣa", "1st person")}
TENSE_MOOD = {
    ("Pres", "Ind"): ("laṭ", "present"), ("Pres", "Imp"): ("loṭ", "imperative"),
    ("Pres", "Opt"): ("vidhiliṅ", "optative"), ("Impf", "Ind"): ("laṅ", "imperfect"),
    ("Past", "Ind"): ("bhūta", "past"), ("Perf", "Ind"): ("liṭ", "perfect"),
    ("Aor", "Ind"): ("luṅ", "aorist"), ("Fut", "Ind"): ("lṛṭ", "future"),
    ("Fut", "Cond"): ("lṛṅ", "conditional"),
    ("Past", "Jus"): ("luṅ (mā-yoga)", "injunctive, with mā"),
    ("Pres", "Ben"): ("āśīrliṅ", "benedictive"),
}
VERBFORM = {"Part": ("kṛdanta (niṣṭhā/śatṛ)", "participle"),
            "Conv": ("ktvā/lyap", "absolutive"), "Inf": ("tumun", "infinitive"),
            "Gdv": ("kṛtya", "gerundive")}
UPOS = {"NOUN": ("nāma", "noun"), "VERB": ("kriyā", "verb"),
        "PRON": ("sarvanāma", "pronoun"), "ADJ": ("viśeṣaṇa", "adjective"),
        "PART": ("nipāta", "particle"), "ADV": ("avyaya", "adverb"),
        "CONJ": ("nipāta", "conjunction"), "SCONJ": ("nipāta", "conjunction"),
        "NUM": ("saṅkhyā", "numeral"), "INTJ": ("nipāta", "interjection"),
        "ADP": ("upasarga/gati", "adposition")}


def describe(upos: str, feats: dict) -> dict:
    sa, en = [], []

    def add(pair):
        if pair:
            sa.append(pair[0]); en.append(pair[1])

    vf = feats.get("VerbForm")
    if upos == "VERB" and "Person" in feats:
        add(TENSE_MOOD.get((feats.get("Tense", "Pres"), feats.get("Mood", "Ind"))))
        if feats.get("Voice") == "Pass":
            add(("karmaṇi", "passive"))
        add(PERSON.get(feats.get("Person")))
        add(NUMBER.get(feats.get("Number")))
    else:
        if vf:
            add(VERBFORM.get(vf))
        else:
            add(UPOS.get(upos))
        add(CASE.get(feats.get("Case")))
        if feats.get("Case") != "Cpd":
            add(GENDER.get(feats.get("Gender")))
            add(NUMBER.get(feats.get("Number")))
    return {"sa": " · ".join(sa), "en": ", ".join(en)}
