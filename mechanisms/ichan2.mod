TITLE ichan2.mod  
 
COMMENT
konduktivitas valtozas hatasa- somaban 
ENDCOMMENT
 
UNITS {
        (mA) =(milliamp)
        (mV) =(millivolt)
        (uF) = (microfarad)
	(molar) = (1/liter)
	(nA) = (nanoamp)
	(mM) = (millimolar)
	(um) = (micron)
	FARADAY = 96520 (coul)
	R = 8.3134	(joule/degC)
}
 
? interface 
NEURON { 
SUFFIX ichan2 
USEION nat READ enat WRITE inat VALENCE 1
USEION kf READ ekf WRITE ikf  VALENCE 1
USEION ks READ eks WRITE iks  VALENCE 1
NONSPECIFIC_CURRENT il 
RANGE  gnat, gkf, gks
RANGE gnatbar, gkfbar, gksbar
RANGE gl, el
RANGE minf, mtau, hinf, htau, nfinf, nftau, inat, ikf, nsinf, nstau, iks
}
 
 
PARAMETER {
	gnatbar (mho/cm2)   
	gkfbar (mho/cm2)
	gksbar (mho/cm2)
}
 
STATE {
	m h nf ns
}
 
ASSIGNED {
        v (mV) 
        celsius (degC)
        enat  (mV)
         
        gnat (mho/cm2) 
        gkf (mho/cm2)
        gks (mho/cm2)

        inat (mA/cm2)
        ikf (mA/cm2)
        iks (mA/cm2)
        
        ekf  (mV)
        eks  (mV)
	gl (mho/cm2)    
 	el (mV)

	il (mA/cm2)

	minf hinf nfinf nsinf
 	mtau (ms) htau (ms) nftau (ms) nstau (ms)
	mexp hexp nfexp nsexp
} 

? currents
BREAKPOINT {
	SOLVE states METHOD cnexp
        gnat = gnatbar*m*m*m*h  
        inat = gnat*(v - enat)
        gkf = gkfbar*nf*nf*nf*nf
        ikf = gkf*(v-ekf)
        gks = gksbar*ns*ns*ns*ns
        iks = gks*(v-eks)

	il = gl*(v-el)
}
 
UNITSOFF
 
INITIAL {
	trates(v)
	
	m = minf
	h = hinf
        nf = nfinf
        ns = nsinf
}

? states
DERIVATIVE states {	:Computes state variables m, h, and n 
    trates(v)	:      at the current v and dt.
    m' = (minf - m) / mtau
    h' = (hinf - h) / htau
    nf' = (nfinf - nf) / nftau
    ns' = (nsinf - ns) / nstau
}
 
? rates
PROCEDURE rates(v) {  :Computes rate and other constants at current v.
                      :Call once from HOC to initialize inf at resting v.
        LOCAL  alpha, beta, sum, q10
       q10 = 3^((celsius - 6.3)/10)
                :"m" sodium activation system - act and inact cross at -40
	alpha = -0.3*vtrap((v+60-17),-5)
	beta = 0.3*vtrap((v+60-45),5)
	sum = alpha+beta        
	mtau = 1/sum      minf = alpha/sum
                :"h" sodium inactivation system
	alpha = 0.23/exptrap(1,(v+60+5)/20)
	beta = 3.33/(1+exptrap(2,(v+60-47.5)/-10))
	sum = alpha+beta
	htau = 1/sum 
        hinf = alpha/sum 
             :"ns" sKDR activation system
        alpha = -0.028*vtrap((v+65-35),-6)
	beta = 0.1056/exptrap(3,(v+65-10)/40)
	sum = alpha+beta        
	nstau = 1/sum      nsinf = alpha/sum
            :"nf" fKDR activation system
        alpha = -0.07*vtrap((v+65-47),-6)
	beta = 0.264/exptrap(4,(v+65-22)/40)
	sum = alpha+beta        
	nftau = 1/sum      nfinf = alpha/sum
	
}
 
PROCEDURE trates(v) {  :Computes rate and other constants at current v.
                      :Call once from HOC to initialize inf at resting v.
	rates(v)	: not consistently executed from here if usetable_hh == 1
		: so don't expect the tau values to be tracking along with
		: the inf values in hoc

}

FUNCTION exptrap(loc,x) {
  if (x>=700.0) {
    :printf("exptrap ichan2 [%g]: x = %g\n", loc, x)
    exptrap = exp(700.0)
  } else {
    exptrap = exp(x)
  }
}
 
FUNCTION vtrap(x,y) {  :Traps for 0 in denominator of rate eqns.
        if (fabs(x/y) < 1e-6) {
                vtrap = y*(1 - x/y/2)
        }else{  
                vtrap = x/(exptrap(0, x/y) - 1)
        }
}
 
UNITSON

