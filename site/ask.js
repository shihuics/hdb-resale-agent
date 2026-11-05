// Turn a plain-English request into map filters, in the browser (no API key needed).
// Example: "4 room under 600k near mrt in the east, cheapest first"
//   -> { flatType: "4 ROOM", maxPrice: 600000, mrt: 500, region: "EAST", sort: "p" }

(function (root) {
  const REGIONS = {
    NORTH: ["SEMBAWANG", "WOODLANDS", "YISHUN"],
    "NORTH-EAST": ["ANG MO KIO", "HOUGANG", "PUNGGOL", "SENGKANG", "SERANGOON"],
    EAST: ["BEDOK", "PASIR RIS", "TAMPINES"],
    WEST: ["BUKIT BATOK", "BUKIT PANJANG", "CHOA CHU KANG", "CLEMENTI", "JURONG EAST", "JURONG WEST"],
    CENTRAL: ["BISHAN", "BUKIT MERAH", "BUKIT TIMAH", "CENTRAL AREA", "GEYLANG", "KALLANG/WHAMPOA",
              "MARINE PARADE", "QUEENSTOWN", "TOA PAYOH"],
  };
  const TOWN_ALIASES = {
    "AMK": "ANG MO KIO", "TPY": "TOA PAYOH", "CCK": "CHOA CHU KANG", "JW": "JURONG WEST",
    "JE": "JURONG EAST", "BB": "BUKIT BATOK", "BP": "BUKIT PANJANG", "SK": "SENGKANG",
    "PR": "PASIR RIS", "KALLANG": "KALLANG/WHAMPOA", "WHAMPOA": "KALLANG/WHAMPOA",
    "CITY": "CENTRAL AREA", "TIONG BAHRU": "BUKIT MERAH", "TELOK BLANGAH": "BUKIT MERAH",
    "BOON LAY": "JURONG WEST", "MARSILING": "WOODLANDS", "ADMIRALTY": "WOODLANDS",
  };
  const FLAT_PATTERNS = [
    [/\b(?:1|one)[\s-]?(?:room|rm)\b/, "1 ROOM"], [/\b(?:2|two)[\s-]?(?:room|rm)\b/, "2 ROOM"],
    [/\b(?:3|three)[\s-]?(?:room|rm)\b/, "3 ROOM"], [/\b(?:4|four)[\s-]?(?:room|rm)\b/, "4 ROOM"],
    [/\b(?:5|five)[\s-]?(?:room|rm)\b/, "5 ROOM"], [/\b(?:exec|executive|ec)\b/, "EXECUTIVE"],
    [/\bmulti[\s-]?gen(?:eration)?\b/, "MULTI-GENERATION"],
  ];

  // "600k", "$600,000", "0.8m", "1.2 mil" -> number of dollars
  function money(s) {
    const m = s.replace(/[$,s\s]/gi, "").match(/^(\d+(?:\.\d+)?)(k|m|mil|million)?$/i);
    if (!m) return null;
    let v = parseFloat(m[1]);
    const unit = (m[2] || "").toLowerCase();
    if (unit === "k") v *= 1e3;
    else if (unit.startsWith("m")) v *= 1e6;
    else if (v < 10) v *= 1e6;        // "under 1" probably means S$1M
    else if (v < 5000) v *= 1e3;      // "under 600" probably means S$600k
    return Math.round(v);
  }

  function parse(text, towns) {
    const raw = text.toLowerCase();
    const q = " " + raw.replace(/[?!]|\.(?!\d)/g, " ") + " ";   // keep decimal points like 1.2
    const out = {}, understood = [];

    for (const [re, t] of FLAT_PATTERNS) if (re.test(q)) { out.flatType = t; understood.push(t.toLowerCase()); break; }

    // Price: "under 600k", "below $450,000", "max 1.2m". Skip distances like "within 300m of MRT".
    const price = q.match(/(?:under|below|less than|max(?:imum)?|up to|<|budget(?: of)?|cheaper than)\s*s?\$?\s*([\d.,]+\s*(?:k|mil|million|m)?)\b(?!\s*(?:of|to|from)?\s*(?:the\s*)?(?:mrt|station|train))/);
    if (price) {
      const v = money(price[1]);
      if (v && v >= 50000) { out.maxPrice = v; understood.push(`under S$${v >= 1e6 ? (v / 1e6) + "M" : Math.round(v / 1000) + "k"}`); }
    }

    // MRT distance: "near mrt" = 500 m; "within 300m of mrt"; "within 1km"
    const dist = q.match(/(?:within|under|less than|<)\s*([\d.]+)\s*(m|km|metres?|meters?)\b[^.]*?\b(?:mrt|station|train)/);
    if (dist) {
      let d = parseFloat(dist[1]);
      if (dist[2].startsWith("k")) d *= 1000;
      out.mrt = Math.round(d); understood.push(`within ${out.mrt.toLocaleString()} m of MRT`);
    } else if (/\b(?:near|close to|next to|walking distance|walkable|beside)\b[^.]*\b(?:mrt|station|train)\b/.test(q) || /\bmrt[\s-]?(?:near|nearby|close)\b/.test(q)) {
      out.mrt = 500; understood.push("within 500 m of MRT");
    }

    const lease = q.match(/(?:at least|min(?:imum)?|more than|over|>|)\s*(\d{2})\s*\+?\s*(?:years?|yrs?)\s*(?:of\s*)?(?:lease|left|remaining)/)
               || q.match(/(?:lease|remaining)\s*(?:of\s*)?(?:at least|over|more than|>)?\s*(\d{2})\s*\+?\s*(?:years?|yrs?)?/);
    if (lease) { out.lease = +lease[1]; understood.push(`${out.lease}+ years lease`); }
    else if (/\b(?:long lease|newer|new flats?|young flats?)\b/.test(q)) { out.lease = 80; understood.push("80+ years lease"); }

    // Region or town
    const regionHit = q.match(/\b(north[\s-]?east|northeast|north|east|west|central|city)\b/);
    let townHit = null;
    const upper = " " + raw.toUpperCase().replace(/[^A-Z/ ]/g, " ") + " ";
    for (const t of [...(towns || [])].sort((a, b) => b.length - a.length)) {
      if (upper.includes(" " + t + " ")) { townHit = t; break; }
    }
    if (!townHit) for (const [alias, t] of Object.entries(TOWN_ALIASES)) {
      if (upper.includes(" " + alias + " ")) { townHit = t; break; }
    }
    if (townHit) { out.towns = [townHit]; understood.push(`in ${title(townHit)}`); }
    else if (regionHit) {
      let r = regionHit[1].toUpperCase().replace(/\s|-/g, "");
      r = r === "NORTHEAST" ? "NORTH-EAST" : r === "CITY" ? "CENTRAL" : r;
      // "north east" written as words may also match "east" first; prefer the longer phrase
      if (/north[\s-]?east|northeast/.test(q)) r = "NORTH-EAST";
      out.towns = REGIONS[r]; out.region = r; understood.push(`${title(r)} region`);
    }

    if (/\b(cheapest|lowest price|most affordable|budget friendly)\b/.test(q)) { out.sort = "p"; understood.push("cheapest first"); }
    else if (/\b(most expensive|priciest|highest price)\b/.test(q)) { out.sort = "-p"; understood.push("priciest first"); }
    else if (/\b(best value|cheapest per|lowest psm|per sqm)\b/.test(q)) { out.sort = "q"; understood.push("lowest price per sqm first"); }
    else if (/\b(closest to|nearest) (?:the )?(?:mrt|station)\b/.test(q)) { out.sort = "md"; understood.push("closest to MRT first"); }
    else if (/\b(most (?:sales|popular|transactions)|popular)\b/.test(q)) { out.sort = "-n"; understood.push("most sales first"); }

    if (/\b(i can afford|can i afford|affordable for me|within my budget|my budget)\b/.test(q)) {
      out.affordable = true; understood.push("only what you can afford");
    }

    // Leftover words that look like a block or street, e.g. "blk 540", "ave 10"
    const blk = q.match(/\b(?:blk|block)\s*(\d+[a-z]?)\b/);
    if (blk) { out.text = blk[1].toUpperCase(); understood.push(`block ${out.text}`); }

    out.understood = understood;
    return out;
  }

  function title(s) { return s.toLowerCase().replace(/\b\w/g, c => c.toUpperCase()); }

  const api = { parse, REGIONS, money };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Ask = api;
})(this);