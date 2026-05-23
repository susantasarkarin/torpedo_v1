import React from 'react'
import { createPortal } from 'react-dom'

function PrivacyModal({ open, onClose }) {
  if (!open) return null
  return createPortal(
    <div style={{position:'fixed',inset:0,background:'rgba(0,0,0,0.5)',display:'flex',alignItems:'center',justifyContent:'center',zIndex:1000}}>
      <div style={{width:'90%',maxWidth:820,background:'white',borderRadius:16,padding:28,maxHeight:'86%',overflow:'auto',boxShadow:'0 30px 80px rgba(0,0,0,0.25)'}}>
        <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:16}}>
          <div style={{display:'flex',alignItems:'center',gap:12}}>
            <img src="/newlogo.png" alt="Cogentix Research" style={{height:34}} />
            <div>
              <h2 style={{margin:0,fontSize:22}}>Cogentix Research Privacy Policy</h2>
              <p style={{margin:0,color:'#6b7280',fontSize:13}}>Last updated: January 2026</p>
            </div>
          </div>
          <button onClick={onClose} style={{background:'transparent',border:'none',fontSize:20,cursor:'pointer'}}>✕</button>
        </div>

        <section style={{color:'#374151',lineHeight:1.75}}>
          <h3 style={{marginTop:0,fontSize:18}}>Data We Collect</h3>
          <ul style={{paddingLeft:18,marginBottom:18}}>
            <li>Identity Data: Name, date of birth, gender</li>
            <li>Contact Data: Email address, phone number</li>
            <li>Survey Data: Responses to survey questions</li>
          </ul>

          <h3 style={{fontSize:18}}>How We Use Your Data</h3>
          <p>We use data to match you with surveys, process rewards, and improve services.</p>

          <h3 style={{fontSize:18}}>Contact</h3>
          <p>For privacy inquiries contact <a href="mailto:privacy@cogentixresearch.com">privacy@cogentixresearch.com</a>.</p>
        </section>
      </div>
    </div>,
    document.body
  )
}

export default PrivacyModal
