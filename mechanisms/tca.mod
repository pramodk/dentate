TITLE T-calcium channel From Migliore CA3
: T-type calcium channel


UNITS {
	(mA) = (milliamp)
	(mV) = (millivolt)

	FARADAY = 96520 (coul)
	R = 8.3134 (joule/degC)
	KTOMV = .0853 (mV/degC)
}

NEURON {
	SUFFIX cat
	USEION tca READ etca WRITE itca VALENCE 2
	USEION ca READ cai, cao VALENCE 2
        RANGE gcatbar,cai, itca, etca
}

PARAMETER {
	gcatbar=.003 (mho/cm2)
	cao (mM)
}


STATE {
	m h 
}

ASSIGNED {
	v (mV)
	celsius	(degC)
	cai (mM)
	itca (mA/cm2)
        gcat (mho/cm2)
	etca (mV)
}

INITIAL {
      m = minf(v)
      h = hinf(v)
}

BREAKPOINT {
	SOLVE states METHOD cnexp
	gcat = gcatbar*m*m*h
	itca = gcat*ghk(v,cai,cao)

}

DERIVATIVE states {	: exact when v held constant
	m' = (minf(v) - m)/m_tau(v)
	h' = (hinf(v) - h)/h_tau(v)
}


FUNCTION ghk(v(mV), ci(mM), co(mM)) (mV) {
        LOCAL nu,f

        f = KTF(celsius)/2
        nu = v/f
        ghk=-f*(1. - (ci/co)*exptrap(1,nu))*efun(nu)
}

FUNCTION KTF(celsius (DegC)) (mV) {
        KTF = ((25./293.15)*(celsius + 273.15))
}


FUNCTION efun(z) {
	if (fabs(z) < 1e-4) {
		efun = 1 - z/2
	}else{
		efun = z/(exptrap(2,z) - 1)
	}
}

FUNCTION hinf(v(mV)) {
	LOCAL a,b
:	TABLE FROM -150 TO 150 WITH 200
	a = 1.e-6*exptrap(3,-v/16.26)
	b = 1/(exptrap(4,(-v+29.79)/10)+1)
	hinf = a/(a+b)
}

FUNCTION minf(v(mV)) {
	LOCAL a,b
:	TABLE FROM -150 TO 150 WITH 200
        
	a = 0.2*(-1.0*v+19.26)/(exptrap(5,(-1.0*v+19.26)/10.0)-1.0)
	b = 0.009*exptrap(6,-v/22.03)
	minf = a/(a+b)
}

FUNCTION m_tau(v(mV)) (ms) {
	LOCAL a,b
:	TABLE FROM -150 TO 150 WITH 200
	a = 0.2*(-1.0*v+19.26)/(exptrap(7,(-1.0*v+19.26)/10.0)-1.0)
	b = 0.009*exptrap(8,-v/22.03)
	m_tau = 1/(a+b)
}

FUNCTION h_tau(v(mV)) (ms) {
	LOCAL a,b
:        TABLE FROM -150 TO 150 WITH 200
	a = 1.e-6*exptrap(9,-v/16.26)
	b = 1/(exptrap(10,(-v+29.79)/10.)+1.)
	h_tau = 1/(a+b)
}

FUNCTION exptrap(loc,x) {
  if (x>=700.0) {
    :printf("exptrap tca [%g]: x = %g\n", loc, x)
    exptrap = exp(700.0)
  } else {
    exptrap = exp(x)
  }
}

