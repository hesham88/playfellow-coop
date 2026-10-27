// Where the live demo service is. null means "not configured": the page then shows only the recorded session and hides the live controls.
// The deploy step writes the real address here (a public address with no secret in it; the service holds the key and checks the origin).
export default { serviceBase: null, turnstileSiteKey: null };
