# Bug report

Bug: The clinic writes a date of birth the caller never gave Severity: High Call: calls/01-schedule-knee-17/transcript.txt at 0:43 Details: Maya Chen had only given her name. The clinic said, "Your patient profile is set up, your date of birth is July fourth two thousand for demo purposes." She had not said a date of birth. On this scenario her date of birth is March 12, 1991. The chart should use only a date the caller provides.

Bug: The clinic books Monday at 9:45 AM before the patient accepts, then keeps that booking after she says she cannot do Monday mornings Severity: High Call: calls/01-schedule-knee-18/transcript.txt at 1:38 Details: Maya asked only to hear the slot again: "Could you repeat the day and time for that earliest appointment?" The clinic answered, "Your appointment is Monday, October nineteenth at nine forty five AM with doctor Adam Bricker at Pivot Point Orthopedics. Would you like me to text you these details?" She then said, "Thanks, but I can't do Monday mornings." At 2:18 the clinic still said, "You already have a new patient appointment. Booked for Monday, October nineteenth at nine forty five AM." It should have offered the time and waited for a yes. After she declined Monday, it should have offered the next morning that is not a Monday and left the Monday slot unbooked.

Bug: Later callers are greeted as Maya because the clinic trusts the caller ID Severity: High Call: calls/02-reschedule/transcript.txt at 0:37 Details: Andre Williams called to move his own Thursday visit. The clinic said, "I see you're calling from the number we have on file. Am I speaking with Maya?" The same greeting is given to Priya Shah in calls/03-cancel/transcript.txt at 0:39, Sam Rivera in calls/04-refill/transcript.txt at 0:26, Luis Ortega in calls/09-correction/transcript.txt at 0:29, and Taylor Nguyen in calls/10-barge-in/transcript.txt at 0:29. It should ask who is calling and open that person's chart.

Bug: A transfer to support hangs up on a test greeting Severity: High Call: calls/02-reschedule/transcript.txt at 1:54 Details: Andre asked to move Thursday at 2 pm to a time after 3:30. The clinic said, "I'll connect you to our patient support team," then "Transferring you now." The next clinic line is, "Hello. You've reached the Pretty Good AI test line. Goodbye." The same ending plays in calls/09-correction/transcript.txt at 2:07 and calls/10-barge-in/transcript.txt at 2:05. The transfer should reach someone who can finish the reschedule or the cancellation.

Bug: A cancellation request never gets a yes or a no Severity: Medium Call: calls/03-cancel/transcript.txt at 1:57 Details: Priya Shah asked to cancel tomorrow morning's left-shoulder visit and said she did not want another booking. The clinic said, "I can't proceed further right now. But I can make sure our clinic support team follows up with you." She declined the transfer. The call ended with no sentence that the visit was canceled and no reason it could not be canceled. It should have confirmed the cancellation or said exactly what was missing.

Bug: A missing chart blocks a new-patient booking Severity: Medium Call: calls/01-schedule-knee-19/transcript.txt at 2:24 Details: Maya Chen gave her name, March 12, 1991, and 415-555-0138, and asked for the earliest weekday morning. After repeating the phone number, the clinic said, "I can't proceed further right now, I can make sure our clinic support team follows up with you." In calls/12-parent-proxy/transcript.txt at 2:06 it told Diane, "I'm unable to book the appointment directly right now because I couldn't find Ethan's record in our system," even though Ethan was a new patient. A missing chart should start a new-patient booking, not stop it.

Bug: The street address is withheld until a date of birth is given Severity: Medium Call: calls/07-hours-location/transcript.txt at 1:32 Details: Chris Dalton asked which office to go to, then "Could you please say the street address for Pivot Point?" The clinic said, "I'll need your date of birth to confirm your appointment location." He said he was not booking an appointment and asked again. At 2:08 the clinic described free parking and still never said a street address. Hours and the Sunday closure were answered correctly earlier in the call. A public address should not require a chart lookup.

Bug: A spelled last name is read back as a different name Severity: Low Call: calls/12-parent-proxy/transcript.txt at 1:24 Details: Diane spelled Okonkwo as O-K-O-N-K-W-O. The clinic read it back as "Ethan Oconquo" and stored that spelling with the caller ID. It should have used the letters she had just given.

<!-- generated:start -->
## Draft from transcripts

These notes were generated from text. A finding counts after you hear it in the recording.

### Heuristic leads

No heuristic leads. That does not mean the calls were clean. Listen anyway.

### Model review

Calls with no transcript bug
<!-- generated:end -->
