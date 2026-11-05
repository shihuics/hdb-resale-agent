// Affordability maths for HDB resale flats. Plain functions, no page code,
// so they can be tested on their own. All amounts in S$.
//
// Rules used (check current values before relying on them):
// - HDB loan: up to 75% of price, max 25 years, must end by age 65,
//   eligibility tested at 3.0% p.a. (actual rate 2.6%), household income ceiling S$14,000.
// - Bank loan: 75% LTV with at least 5% in cash; 55% LTV (10% cash) if tenure is over
//   25 years or runs past age 65. Eligibility tested at 4.0% p.a. Max 30 years.
// - Mortgage Servicing Ratio (MSR): instalment at the test rate <= 30% of gross monthly income.
// - Lease and CPF: if the remaining lease doesn't cover the youngest buyer to age 95,
//   CPF use (and the HDB loan limit) is pro-rated: share = (lease - 20) / (75 - age).
//   No CPF at all if the remaining lease is under 20 years. This matches the official
//   2019 MND/MOM worked example (age 25: lease 65 -> 90%, lease 55 -> 70%).
// - Buyer's stamp duty (BSD) on residential property: 1% / 2% / 3% / 4% / 5% / 6% bands.

(function (root) {
  const RULES = {
    msr: 0.30,
    hdb: { ltv: 0.75, maxYears: 25, testRate: 0.03, incomeCeiling: 14000, minCash: 0 },
    bank: { ltv: 0.75, lowLtv: 0.55, maxYears: 30, lowLtvAfterYears: 25, testRate: 0.04,
            minCash: 0.05, lowLtvMinCash: 0.10 },
    loanEndAge: 65,
    cpfFullAge: 95,
    minLeaseForCpf: 20,
  };

  // Present value of a monthly instalment over `years` at annual `rate`
  function loanFromInstalment(monthly, rate, years) {
    const n = Math.round(years * 12), r = rate / 12;
    if (n <= 0) return 0;
    return r === 0 ? monthly * n : monthly * (1 - Math.pow(1 + r, -n)) / r;
  }

  function instalment(loan, rate, years) {
    const n = Math.round(years * 12), r = rate / 12;
    if (n <= 0) return Infinity;
    return r === 0 ? loan / n : loan * r / (1 - Math.pow(1 + r, -n));
  }

  // Share of the CPF limit usable, given remaining lease at purchase and youngest buyer's age
  function cpfShare(leaseYears, age) {
    const needed = RULES.cpfFullAge - age;
    if (leaseYears >= needed) return 1;
    if (leaseYears < RULES.minLeaseForCpf) return 0;
    return Math.max(0, Math.min(1, (leaseYears - RULES.minLeaseForCpf) / (needed - RULES.minLeaseForCpf)));
  }

  function stampDuty(price) {
    const bands = [[180000, 0.01], [180000, 0.02], [640000, 0.03], [500000, 0.04], [1500000, 0.05], [Infinity, 0.06]];
    let left = price, duty = 0;
    for (const [size, rate] of bands) {
      const part = Math.min(left, size);
      duty += part * rate;
      left -= part;
      if (left <= 0) break;
    }
    return Math.round(duty);
  }

  // Loan term and loan-to-value limit for this buyer
  function loanTerms(p) {
    const ageCap = Math.max(0, RULES.loanEndAge - p.age);
    if (p.loanType === "hdb") {
      const years = Math.min(p.years || RULES.hdb.maxYears, RULES.hdb.maxYears, ageCap);
      return { years, ltv: RULES.hdb.ltv, minCash: RULES.hdb.minCash, testRate: RULES.hdb.testRate };
    }
    const wanted = Math.min(p.years || 25, RULES.bank.maxYears);
    const years = wanted;  // bank tenure may run past 65, but then the lower LTV applies
    const low = years > RULES.bank.lowLtvAfterYears || p.age + years > RULES.loanEndAge;
    return { years, ltv: low ? RULES.bank.lowLtv : RULES.bank.ltv,
             minCash: low ? RULES.bank.lowLtvMinCash : RULES.bank.minCash, testRate: RULES.bank.testRate,
             lowLtv: low };
  }

  // Can this buyer afford a flat at `price` with `leaseYears` remaining?
  // p = { income, cash, cpf, age, loanType: "hdb" | "bank", years, rate }
  function assess(p, price, leaseYears) {
    const t = loanTerms(p);
    const share = cpfShare(leaseYears, p.age);
    // HDB pro-rates its loan limit the same way as CPF; banks apply their own LTV rules
    const ltv = p.loanType === "hdb" ? t.ltv * share : t.ltv;
    const msrLoan = loanFromInstalment(RULES.msr * p.income, t.testRate, t.years);
    const loan = Math.max(0, Math.min(ltv * price, msrLoan));
    const bsd = stampDuty(price);
    const cpfLimit = share * price;                 // CPF usable towards the price
    const minCash = t.minCash * price;
    const towardsPrice = price - loan;              // downpayment + any shortfall
    const cpfForPrice = Math.min(p.cpf, cpfLimit, Math.max(0, towardsPrice - minCash));
    const cpfLeft = p.cpf - cpfForPrice;
    const cpfForBsd = Math.min(cpfLeft, bsd);       // stamp duty can be paid with CPF OA
    const cashNeeded = (towardsPrice - cpfForPrice) + (bsd - cpfForBsd);
    const monthly = instalment(loan, p.rate ?? (p.loanType === "hdb" ? 0.026 : 0.03), t.years);
    return {
      price, leaseYears, loan, ltvUsed: price ? loan / price : 0, ltvLimit: ltv, msrLoan,
      limitedBy: loan >= ltv * price - 1 ? "ltv" : "income",
      share, cpfForPrice, cpfForBsd, bsd, cashNeeded, monthly, years: t.years,
      shortBy: Math.max(0, cashNeeded - p.cash),
      ok: cashNeeded <= p.cash && t.years > 0,
      noHdbLoan: p.loanType === "hdb" && p.income > RULES.hdb.incomeCeiling,
      noCpf: share === 0,
      lowLtv: !!t.lowLtv,
    };
  }

  // Highest price affordable for a flat whose lease covers the buyer to 95 (full CPF)
  function budget(p) {
    let lo = 0, hi = 5e6;
    for (let i = 0; i < 40; i++) {
      const mid = (lo + hi) / 2;
      if (assess(p, mid, 99).ok) lo = mid; else hi = mid;
    }
    return Math.floor(lo / 1000) * 1000;
  }

  const api = { RULES, cpfShare, stampDuty, loanFromInstalment, instalment, loanTerms, assess, budget };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Afford = api;
})(this);