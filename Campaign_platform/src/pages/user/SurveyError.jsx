import "./TrafficFlowParser.css";

export default function SurveyError() {
  return (
    <div className="survey-container">
      <div className="survey-card">
        <img 
          src="/images/SF.png" 
          alt="SurveyFieldwork Logo" 
          className="survey-logo" 
        />
        <h1 className="survey-title">Thank You for Your Time</h1>
        <hr className="survey-divider" />
        <p className="survey-text">
          Unfortunately, you haven't qualified for any surveys at this time. 
          We hope you'll try again later.
        </p>
      </div>
    </div>
  );
}
